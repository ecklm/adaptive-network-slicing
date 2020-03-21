import json
from copy import deepcopy
from typing import Tuple

import requests
from ryu.controller import controller

from flow import *


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
        Set the address of the openvswitch database to the controller.

        This MUST be called once before sending configuration commands.
        """
        r = requests.put("http://localhost:8080/v1.0/conf/switches/%016x/ovsdb_addr" % self.__datapath.id,
                         data='"tcp:192.0.2.20:6632"',
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.log_rest_result(r)

    def set_queues(self):
        # Extract port names and drop internal port named equivalently as the switch
        ports = sorted([port.name.decode('utf-8') for port in self.__datapath.ports.values()])[1:]
        self.__logger.debug("Ports to be configured: {}".format(ports))
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
        Set queus in the switch.

        WARNING: This request MUST be run some time after setting the OVSDB address to the controller.
        If it is run too soon, the controller responds with a failure.
        Calling this function right after setting the OVSDB address will result in occasional failures.
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
        Log rules already installed in the switch.

        WARNING: This call makes the switch send an OpenFlow statsReply message,
        which triggers every function subscribed to the ofp_event.EventOFPFlowStatsReply
        event.
        """
        r = requests.get("http://localhost:8080/qos/rules/%016x" % self.__datapath.id)
        self.log_rest_result(r)

    def get_current_limit(self, flow: FlowId) -> int:
        """
        Get current limit for a specific flow.

        :return: The current rate limit applied to `flow` in bits/s.
        """
        return self.flows_limits[flow][0]

    def _update_limit(self, flow: FlowId, newlimit, force: bool = False) -> bool:
        """
        Update the limit of a queue related to `flow`.

        The function will only update the value if `newlimit` is further from the actual limit than `LIMIT_STEP` b/s.

        :param flow: The flow identifier to set new limit to.
        :param newlimit: The new rate limit for `flow` in bits/s.
        :param force: Force updating the limit even if the difference is smaller than `LIMIT_STEP`.
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
