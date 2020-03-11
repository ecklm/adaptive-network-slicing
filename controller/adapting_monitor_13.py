from typing import Dict, Tuple

from ryu.base import app_manager
from ryu.controller import ofp_event, controller
from ryu.ofproto import ofproto_v1_3
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
import requests
import json
from dataclasses import dataclass
from copy import deepcopy


@dataclass(frozen=True)
class FlowId:
    ipv4_dst: str
    udp_dst: int


class AdaptingMonitor13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    time_step = 5  # The number of seconds between two stat request
    flows_limits = {
        FlowId('10.0.0.1', 5001): 5 * 10 ** 6,
        FlowId('10.0.0.1', 5002): 15 * 10 ** 6,
        FlowId('10.0.0.1', 5003): 25 * 10 ** 6
    }

    def __init__(self, *args, **kwargs):
        super(AdaptingMonitor13, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.qos_managers: Dict[int, QoSManager] = {}  # Key: datapath id
        self.stats: Dict[int, FlowStatManager] = {}  # Key: datapath id
        self.monitor_thread = hub.spawn(self._monitor)

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


class QoSManager:
    # The smallest difference in b/s that can result in rate limit changing in a queue. This
    # helps to perform histeresys in the adapting logic
    LIMIT_STEP = 2 * 10 ** 6
    DEFAULT_MAX_RATE = -1

    def __init__(self, datapath: controller.Datapath, flows_with_init_limits: Dict[FlowId, int], logger):
        self.__datapath = datapath

        self.flows_limits: Dict[FlowId, Tuple[int, int]] = {}  # This will hold the actual values updated

        # Start from qnume = 1 so that the matches to the first rule does not get the same queue as non-matches
        flows_initlims_enum = enumerate(flows_with_init_limits, start=1)
        for qnum, k in flows_initlims_enum:
            self.flows_limits[k] = (flows_with_init_limits[k], qnum)
        self.FLOWS_INIT_LIMITS: Dict[FlowId, Tuple[int, int]] = \
            deepcopy(self.flows_limits)  # This does not change, it contains the values of the ideal, "customer" case

        self.__logger = logger
        self.__set_ovsdb_addr()
        self.set_rules()
        self.set_queues()

    def __set_ovsdb_addr(self):
        """
        This method sets the address of the openvswitch database to the controller. This MUST be called once before
        sending configuration commands.
        """
        r = requests.put("http://localhost:8080/v1.0/conf/switches/%016x/ovsdb_addr" % self.__datapath.id,
                         data='"tcp:192.0.2.20:6632"',
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.log_rest_result(r)

    def set_queues(self):
        ports = [port.name.decode('utf-8') for port in self.__datapath.ports.values()][:-1]  # Last element is the
        # switch itself
        queue_limits = [QoSManager.DEFAULT_MAX_RATE] + [self.flows_limits[k][0] for k in self.flows_limits]
        for port in ports:
            r = requests.post("http://localhost:8080/qos/queue/%016x" % self.__datapath.id,
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  "port_name": port, "type": "linux-htb", "max_rate": str(QoSManager.DEFAULT_MAX_RATE),
                                  "queues":
                                      [{"max_rate": str(limit)} for limit in queue_limits]
                              }))
            self.log_rest_result(r)

    def get_queues(self):
        """
        WARNING: This request MUST be run some time after setting the OVSDB address to the controller.
        If it is run too soon, the controller responds with a failure.
        Calling this function right after setting the OVSDB address will result in occasional failures
        """
        r = requests.get("http://localhost:8080/qos/queue/%016x" % self.__datapath.id)
        self.log_rest_result(r)

    def adapt_queues(self, flowstats: Dict[FlowId, float]):
        modified = False
        unused_candidates = [k for k, v in flowstats.items() if v < self.FLOWS_INIT_LIMITS[k][0] / 2]
        used_candidates = [k for k, v in flowstats.items() if v > self.FLOWS_INIT_LIMITS[k][0] / 2]
        self.__logger.debug("unused:\t%s\nused:\t%s\nrest (virtually impossible):\t%s" %
                            (unused_candidates,
                             used_candidates,
                             [k for k, v in flowstats.items() if v == self.FLOWS_INIT_LIMITS[k][0] / 2]))
        overall_gain = 0  # b/s which is available extra after rate reduction
        for k in unused_candidates:
            original_limit = self.FLOWS_INIT_LIMITS[k][0]
            if self._update_limit(k, original_limit / 2):
                modified = True
            overall_gain += original_limit - self.get_current_limit(k)

        try:
            available_per_host = overall_gain / len(used_candidates)
        except ZeroDivisionError:
            available_per_host = 0
        for k in used_candidates:
            if (self._update_limit(k, self.FLOWS_INIT_LIMITS[k][0] + available_per_host)):
                modified = True
        if modified:
            self.set_queues()

    def set_rules(self):
        for k in self.flows_limits:
            r = requests.post("http://localhost:8080/qos/rules/%016x" % self.__datapath.id,
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  "match": {
                                      "nw_dst": k.ipv4_dst,
                                      "nw_proto": "UDP",
                                      "tp_dst": k.udp_dst,
                                  },
                                  "actions": {"queue": self.flows_limits[k][1]}
                              }))
            self.log_rest_result(r)

    def get_rules(self):
        """
        WARNING: This call makes the switch send an OpenFlow statsReply message,
        which triggers every function subscribed to the ofp_event.EventOFPFlowStatsReply
        event.
        """

        r = requests.get("http://localhost:8080/qos/rules/%016x" % self.__datapath.id)
        self.log_rest_result(r)

    def get_current_limit(self, flow: FlowId) -> int:
        """
        :return: The current rate limit applied to `flow` in bits/s
        """
        return self.flows_limits[flow][0]

    def _update_limit(self, flow: FlowId, newlimit, force: bool = False) -> bool:
        """
        Update the limit of a queue related to `flow`. The function will only update the value if `newlimit` is
        further from the actual limit than `LIMIT_STEP` b/s.

        :param flow: The flow identifier to set new limit to.
        :param newlimit: The new rate limit for `flow` in bits/s
        :param force: Force updating the limit even if the difference is smaller than `LIMIT_STEP`
        :return: Whether the limit is updated or not
        """
        if abs(newlimit - self.get_current_limit(flow)) > QoSManager.LIMIT_STEP or force:
            self.flows_limits[flow] = (int(newlimit), self.flows_limits[flow][1])
            self.__logger.info("Flow limit for flow '{}' updated to {}bps".format(flow, newlimit))
            return True
        else:
            return False

    def log_rest_result(self, r: requests.Response) -> None:
        if r.status_code >= 300 or \
                -1 != r.text.find("failure"):
            log = self.__logger.error
        else:
            log = self.__logger.debug
        try:
            log("{} - {}".format(r.status_code,
                                 json.dumps(r.json(), indent=4, sort_keys=True)))
        except ValueError:
            log("{} - {}".format(r.status_code, r.text))


class FlowStat:
    window_size = 10  # The number of data stored for statistical calculations
    scaling_prefixes = {'K': 1 / 1000, 'M': 1 / 1000000, 'G': 1 / 1000000000, None: 1}

    def __init__(self, time_step: int):
        """
        :param time_step: The number of seconds between two measurements.
        """
        self.data = []
        self.time_step = time_step

    def put(self, val: int):
        if len(self.data) < FlowStat.window_size:
            self.data.append(val)
        else:
            self.data = self.data[1:] + [val]

    def get_avg(self, prefix: str = None) -> float:
        """
        :param prefix: A prefix to scale the result with. See possible values in `FlowStat.scaling_prefixes`
        :return: The average number of bytes transmitted during the last `window_size` number of measurements
        """
        if len(self.data) == 0:
            return 0
        elif len(self.data) == 1:
            # This number will not necessarily make sense, but at least it may prevent the QoS manager from decreasing
            # the limits for all flows at the first measurement
            return self.data[0]
        else:
            return (self.data[-1] - self.data[0]) * FlowStat.scaling_prefixes[prefix] / float(len(self.data) - 1)

    def get_avg_speed(self, prefix: str = None) -> float:
        """
        :param prefix: See `FlowStat.get_avg` parameter documentation
        :return: The average throughput of the Flow during the last `window_size` number of measurements in **Bytes/s**
        """
        return self.get_avg(prefix) / float(self.time_step)

    def get_avg_speed_bps(self, prefix: str = None) -> float:
        """
        :param prefix: See `FlowStat.get_avg` parameter documentation
        :return: The average throughput of the Flow during the last `window_size` number of measurements in **bits/s**
        """
        return self.get_avg_speed(prefix) * 8


class FlowStatManager:
    def __init__(self, time_step):
        self.stats: Dict[FlowId, FlowStat] = {}
        self.time_step = time_step

    def put(self, flow: FlowId, val: int) -> None:
        """
        Adds a new record to the specified flow's stats

        :param flow: The identifier of the Flow
        :param val: The measurement value
        """
        try:
            self.stats[flow].put(val)
        except KeyError:
            self.stats[flow] = FlowStat(self.time_step)
            self.stats[flow].put(val)

    def get_avg(self, flow: FlowId, prefix: str = None) -> float:
        """
        :param prefix: See `FlowStat.get_avg` parameter documentation
        :return: The result of `FlowStat.get_avg` for the given flow
        """
        return self.stats[flow].get_avg(prefix)  # Let the KeyError exception arise if any

    def get_avg_speed(self, flow: FlowId, prefix: str = None) -> float:
        """
        :param prefix: See `FlowStat.get_avg` parameter documentation
        :return: The result of `FlowStat.get_avg_speed` for the given flow
        """
        return self.stats[flow].get_avg_speed(prefix)

    def get_avg_speed_bps(self, flow: FlowId, prefix: str = None) -> float:
        """
        :param prefix: See `FlowStat.get_avg` parameter documentation
        :return: The result of `FlowStat.get_avg_bps` for the given flow
        """
        return self.stats[flow].get_avg_speed_bps(prefix)

    def export_avg_speeds(self, prefix: str = None) -> Dict[FlowId, float]:
        return {k: v.get_avg_speed(prefix) for (k, v) in self.stats.items()}

    def export_avg_speeds_bps(self, prefix: str = None) -> Dict[FlowId, float]:
        return {k: v.get_avg_speed_bps(prefix) for (k, v) in self.stats.items()}
