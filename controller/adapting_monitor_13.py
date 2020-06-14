import logging
from os import environ as env

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

from flow import *
from qos_manager import QoSManager, ThreadedQoSManager


class AdaptingMonitor13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    TIME_STEP = 5  # The number of seconds between two stat request
    FLOWS_LIMITS: Dict[FlowId, int] = {}  # Rate limits associated to different flows
    LOG_STAT_SEQUENCE_DELIMITER = "=" * 50
    STAT_LOG_FORMAT = "csv"

    def __init__(self, *args, **kwargs):
        super(AdaptingMonitor13, self).__init__(*args, **kwargs)

        self.logger = logging.getLogger("adapting_monitor")

        config_file = env.get("CONFIG_FILE", "configs/default.yml")
        self.logger.info("Using %s as config file.", config_file)
        self.configure(config_file)

        self.datapaths = {}
        self.qos_manager = ThreadedQoSManager(AdaptingMonitor13.FLOWS_LIMITS)
        self.stats: Dict[int, FlowStatManager] = {}  # Key: datapath id

    def start(self):
        super(AdaptingMonitor13, self).start()
        self.logger.info(self.__class__.LOG_STAT_SEQUENCE_DELIMITER)
        self.threads.append(hub.spawn(self._monitor))
        self.threads.append(hub.spawn(self._adapt))
        self.threads.append(hub.spawn(self._flow_stats_logger))

    def stop(self):
        super().stop()
        self.logger.info(self.__class__.LOG_STAT_SEQUENCE_DELIMITER)

    def _monitor(self):
        self.logger.info("Network monitoring started.")
        while self.is_active:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(AdaptingMonitor13.TIME_STEP)
        self.logger.info("Network monitoring stopped.")

    def _adapt(self):
        self.logger.info("Queue adaptation loop started.")
        while self.is_active:
            # To make adaptation global to the network, the QoSManager need to see a projection of flowstats that has
            # the maximum measured value for each flow, thus accumulating the measurements from all datapaths.
            flowstat_max_per_flow: Dict[FlowId, float] = {}
            for fsm in list(self.stats.values()):
                for fid, avg_speed in fsm.export_avg_speeds_bps().items():
                    if fid not in flowstat_max_per_flow or \
                            avg_speed > flowstat_max_per_flow[fid]:
                        flowstat_max_per_flow[fid] = avg_speed
            if flowstat_max_per_flow:
                self.qos_manager.adapt_queues(flowstat_max_per_flow, False)
            hub.sleep(AdaptingMonitor13.TIME_STEP)
        self.logger.info("Queue adaptation loop stopped.")

    @classmethod
    def configure(cls, config_path: str) -> None:
        """
        Configure the application based on the values in the file available at `config_path`.

        A few exceptions are not caught on purpose. `config_handler.ConfigError` is raised when there is some problem
        with the config file, as it should definitely result in application failure.

        :param config_path: Path to the configuration file
        """
        logger = logging.getLogger("config")

        ch = config_handler.ConfigHandler(config_path)
        # Don't catch exception on purpose, bad config => Not working app

        # Mandatory fields
        for flow in ch.config["flows"]:
            try:
                new_flow_id = FlowId.from_dict(flow)
                cls.FLOWS_LIMITS[new_flow_id] = flow["base_ratelimit"]
                logger.info("flow configuration added: ({}, {})".format(
                    new_flow_id, flow["base_ratelimit"])
                )
            except (TypeError, KeyError) as e:
                logger.error("Invalid Flow object: {}. Reason: {}".format(flow, e))
        if len(cls.FLOWS_LIMITS) <= 0:
            raise config_handler.ConfigError("config: No valid flow definition found.")

        # Optional fields
        if "time_step" in ch.config:
            cls.TIME_STEP = int(ch.config["time_step"])
            logger.info("time_step set to {}".format(cls.TIME_STEP))
        else:
            logger.debug("time_step not set")

        if "stat_log_format" in ch.config:
            cls.STAT_LOG_FORMAT = ch.config["stat_log_format"]
            logger.info("stat_log_format set to {}".format(cls.STAT_LOG_FORMAT))
        else:
            logger.debug("stat_log_format not set")

        # Configure other classes
        QoSManager.configure(ch)
        FlowStat.configure(ch)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
                # Ports list always has one element with the name of the switch itself and the rest with actual port
                # names.
                all_ports = sorted([port.name.decode('utf-8') for port in datapath.ports.values()])
                datapath.cname = all_ports[0]
                datapath.ports = all_ports[1:]
                self.stats[datapath.id] = FlowStatManager()
                self.qos_manager.set_ovsdb_addr(datapath.id, blocking=True)
                self.qos_manager.set_rules(datapath.id, blocking=True)
                self.qos_manager.set_queues(datapath.id, blocking=False)  # Blocking=False will make it not run
                # unnecessarily when a global queue adaptation is in progress.
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]
                del self.stats[datapath.id]

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    def _flow_stats_logger(self):
        while self.is_active:
            # Collect and order entries
            statentries = []
            for dpid, flowstats in self.stats.items():
                for flow, avg_speed in flowstats.export_avg_speeds_bps('M').items():
                    statentries.append((dpid, self.datapaths[dpid].cname,
                                        flow.ipv4_dst, flow.udp_dst,
                                        avg_speed,
                                        self.qos_manager.get_current_limit(flow) / 10 ** 6,
                                        self.qos_manager.get_initial_limit(flow) / 10 ** 6))
            # Sort by flows first and then by dpid (=switch)
            statentries = sorted(statentries, key=lambda entry: (entry[2:4], entry[0]))

            # Print stat log
            header_fields = ('datapath', 'ipv4-dst', 'udp-dst', 'avg-speed (Mb/s)', 'current limit (Mb/s)',
                             'initial limit (Mb/s)')
            if self.__class__.STAT_LOG_FORMAT == "human":
                # Print log header
                self.logger.info("")
                self.logger.info('%10s %10s %7s %16s %20s %20s' % header_fields)
                self.logger.info('%s %s %s %s %s %s' %
                                 ('-' * 10, '-' * 10, '-' * 7, '-' * 16, '-' * 20, '-' * 20))
                # Log statistics
                for entry in statentries:
                    self.logger.info('%10s %10s %7d %16.2f %20.2f %20.2f' % entry[1:])  # [1:] -> without dpid
            elif self.__class__.STAT_LOG_FORMAT == "csv":
                # self.logger.info(",".join(header_fields))
                for entry in statentries:
                    entry = [str(field) for field in entry]
                    self.logger.info(",".join(entry[1:]))
            else:
                raise ValueError("Invalid STAT_LOG_FORMAT set: %s" % self.__class__.STAT_LOG_FORMAT)

            hub.sleep(1)

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
