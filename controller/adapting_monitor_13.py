from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

import config_handler
from flow import *
from qos_manager import QoSManager


class AdaptingMonitor13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    time_step = 5  # The number of seconds between two stat request
    flows_limits: Dict[FlowId, int] = {}  # Rate limits associated to different flows

    def __init__(self, *args, **kwargs):
        super(AdaptingMonitor13, self).__init__(*args, **kwargs)

        self.configure("config.yml")

        self.datapaths = {}
        self.qos_managers: Dict[int, QoSManager] = {}  # Key: datapath id
        self.stats: Dict[int, FlowStatManager] = {}  # Key: datapath id
        self.monitor_thread = hub.spawn(self._monitor)

    def configure(self, config_path: str) -> None:
        """
        Configure the application based on the values in the file available at `config_path`.

        A few exceptions are not caught on purpose. `config_handler.ConfigError` is raised when there is some problem
        with the config file and it should definitely result in application failure.
        `

        :param config_path: Path to the configuration file
        """
        config = config_handler.ConfigHandler(config_path)
        # Don't catch exception on purpose, bad config => Not working app

        config = config.config
        # Mandatory fields
        for flow in config["flows"]:
            try:
                AdaptingMonitor13.flows_limits[FlowId.from_dict(flow)] = flow["base_ratelimit"]
            except (TypeError, KeyError) as e:
                self.logger.error("config: Invalid Flow object: {}. Reason: {}".format(flow, e))
        if len(AdaptingMonitor13.flows_limits) <= 0:
            raise config_handler.ConfigError("config: No valid flow definition found.")

        QoSManager.CONTROLLER_BASEURL = config["controller_baseurl"]
        self.logger.debug("config: controller_baseurl set to {}".format(QoSManager.CONTROLLER_BASEURL))

        if type(config["ovsdb_addr"]) == str:
            QoSManager.OVSDB_ADDR = config["ovsdb_addr"]
            self.logger.debug("config: ovsdb_addr set to {}".format(QoSManager.OVSDB_ADDR))
        else:
            raise TypeError("config: ovsdb_addr must be string")

        # Optional fields
        if "time_step" in config:
            AdaptingMonitor13.time_step = int(config["time_step"])
            self.logger.debug("config: time_step set to {}".format(AdaptingMonitor13.time_step))
        else:
            self.logger.debug("config: time_step not set")

        if "limit_step" in config:
            QoSManager.LIMIT_STEP = int(config["limit_step"])
            self.logger.debug("config: limit_step set to {}".format(QoSManager.LIMIT_STEP))
        else:
            self.logger.debug("config: limit_step not set")

        if "interface_max_rate" in config:
            QoSManager.DEFAULT_MAX_RATE = int(config["interface_max_rate"])
            self.logger.debug("config: interface_max_rate set to {}".format(QoSManager.DEFAULT_MAX_RATE))
        else:
            self.logger.debug("config: interface_max_rate not set")

        if "flowstat_window_size" in config:
            FlowStat.window_size = int(config["flowstat_window_size"])
            self.logger.debug("config: flowstat_window_size set to {}".format(FlowStat.window_size))
        else:
            self.logger.debug("config: flowstat_window_size not set")

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
                self.qos_managers[datapath.id] = QoSManager(datapath, AdaptingMonitor13.flows_limits, self.logger)
                self.stats[datapath.id] = FlowStatManager(AdaptingMonitor13.time_step)
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]
                del self.qos_managers[datapath.id]
                del self.stats[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(AdaptingMonitor13.time_step)

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_logger(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        flowstats = sorted([flow for flow in body if flow.priority == 1 and flow.table_id == 0],
                           key=lambda flow: (flow.match['ipv4_dst'], flow.match['udp_dst']))
        if len(flowstats) > 0:
            self.logger.info("")
            self.logger.info('%16s %10s %7s %8s %8s %11s %16s %20s' %
                             ('datapath', 'ipv4-dst', 'udp-dst', 'queue-id', 'packets',
                              'bytes', 'avg-speed (Mb/s)', 'current-limit (Mb/s)'))
            self.logger.info('%s %s %s %s %s %s %s %s' %
                             ('-' * 16, '-' * 10, '-' * 7, '-' * 8, '-' * 8, '-' * 11, '-' * 16, '-' * 20))
        for stat in flowstats:
            flow = FlowId(stat.match['ipv4_dst'], stat.match['udp_dst'])
            avg_speed = self.stats[dpid].get_avg_speed_bps(flow, 'M')
            self.logger.info('%016x %10s %7d %8d %8d %11d %16.2f %20.2f',
                             dpid,
                             stat.match['ipv4_dst'], stat.match['udp_dst'],
                             stat.instructions[0].actions[0].queue_id,
                             stat.packet_count, stat.byte_count, avg_speed,
                             self.qos_managers[dpid].get_current_limit(flow) / 10 ** 6)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        flowstats = sorted([flow for flow in body if flow.priority == 1 and flow.table_id == 0],
                           key=lambda flow: (flow.match['ipv4_dst'], flow.match['udp_dst']))
        dpid = ev.msg.datapath.id
        for stat in flowstats:
            # WARNING: stat.byte_count is the number of bytes that MATCHED the rule, not the number of bytes
            # that have finally been transmitted. This is not a problem for us, but it is important to know
            flow = FlowId(stat.match['ipv4_dst'], stat.match['udp_dst'])
            self.stats[dpid].put(flow, stat.byte_count)
        self.qos_managers[dpid].adapt_queues(self.stats[dpid].export_avg_speeds_bps())
