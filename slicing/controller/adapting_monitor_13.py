from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.ofproto import ofproto_v1_3
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
import requests
import json


class AdaptingMonitor13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(AdaptingMonitor13, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.qos_managers = {}
        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.debug('register datapath: %016x', datapath.id)
                self.datapaths[datapath.id] = datapath
                self.qos_managers[datapath.id] = QoSManager(datapath.id, self.logger)
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.debug('unregister datapath: %016x', datapath.id)
                del self.datapaths[datapath.id]
                del self.qos_managers[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(5)

    def _request_stats(self, datapath):
        self.logger.debug('send stats request: %016x', datapath.id)
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_logger(self, ev):
        body = ev.msg.body

        flowstats = sorted([flow for flow in body if flow.priority == 1 and flow.table_id == 0],
                           key=lambda flow: (flow.match['ipv4_dst'], flow.match['udp_dst']))
        if len(flowstats) > 0:
            self.logger.info("")
            self.logger.info('datapath         '
                             'ipv4-dst   udp-dst '
                             'queue-id packets  bytes')
            self.logger.info('---------------- '
                             '---------- ------- '
                             '-------- -------- -----------')
        for stat in flowstats:
            self.logger.info('%016x %10s %7d %8d %8d %11d',
                             ev.msg.datapath.id,
                             stat.match['ipv4_dst'], stat.match['udp_dst'],
                             stat.instructions[0].actions[0].queue_id,
                             stat.packet_count, stat.byte_count)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body


class QoSManager:
    queue_setting = {"port_name": "s1-eth1", "type": "linux-htb", "max_rate": "50000000",
                     "queues":
                         [{"max_rate": "5000000"}, {"max_rate": "15000000"}, {"max_rate": "25000000"}]
                     }

    def __init__(self, datapath: int, logger):
        self.__datapath = datapath
        self.__logger = logger
        self.__set_ovsdb_addr()
        self.set_rules()
        self.set_queues()

    def __set_ovsdb_addr(self):
        """
        This method sets the address of the openvswitch database to the controller. This MUST be called once before
        sending configuration commands.
        """
        r = requests.put("http://localhost:8080/v1.0/conf/switches/%016d/ovsdb_addr" % self.__datapath,
                         data='"tcp:192.0.2.20:6632"',
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.log_rest_result(r)

    def set_queues(self):
        r = requests.post("http://localhost:8080/qos/queue/%016d" % self.__datapath,
                          data=json.dumps(QoSManager.queue_setting),
                          headers={'Content-Type': 'application/json'})
        self.log_rest_result(r)

    def get_queues(self):
        """
        WARNING: This request MUST be run some time after setting the OVSDB address to the controller.
        If it is run too soon, the controller responds with a failure.
        Calling this function right after setting the OVSDB address will result in occasional failures
        """
        r = requests.get("http://localhost:8080/qos/queue/%016d" % self.__datapath)
        self.log_rest_result(r)

    def set_rules(self):
        for dport, queue in [(5001, 0), (5002, 1), (5003, 2)]:
            r = requests.post("http://localhost:8080/qos/rules/%016d" % self.__datapath,
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  "match": {
                                      "nw_dst": "10.0.0.1",
                                      "nw_proto": "UDP",
                                      "tp_dst": dport,
                                  },
                                  "actions": {"queue": queue}
                              }))
            self.log_rest_result(r)

    def get_rules(self):
        """
        WARNING: This call makes the switch send an OpenFlow statsReply message,
        which triggers every function subscribed to the ofp_event.EventOFPFlowStatsReply
        event.
        """

        r = requests.get("http://localhost:8080/qos/rules/%016d" % self.__datapath)
        self.log_rest_result(r)

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
