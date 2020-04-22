import json
from copy import deepcopy
from typing import Tuple
from math import ceil

import requests
from ryu.controller import controller

from flow import *


class QoSManager:
    # The smallest difference in b/s that can result in rate limit changing in a queue. This
    # helps to perform hysteresis in the adapting logic
    LIMIT_STEP = 2 * 10 ** 6
    DEFAULT_MAX_RATE = -1  # Max rate to be set on a queue if not told otherwise.
    OVSDB_ADDR: str  # Address of the OVS database
    CONTROLLER_BASEURL: str  # Base URL where the controller can be reached.

    @classmethod
    def configure(cls, ch: config_handler.ConfigHandler, logger) -> None:
        """
        Configure common class values based on the config file.

        :param ch: The config_handler object.
        :param logger: Logger to log messages to.
        """
        # Mandatory fields
        cls.CONTROLLER_BASEURL = ch.config["controller_baseurl"]
        logger.info("config: controller_baseurl set to {}".format(cls.CONTROLLER_BASEURL))

        if type(ch.config["ovsdb_addr"]) == str:
            cls.OVSDB_ADDR = ch.config["ovsdb_addr"]
            logger.debug("config: ovsdb_addr set to {}".format(cls.OVSDB_ADDR))
        else:
            raise TypeError("config: ovsdb_addr must be string")

        # Optional fields
        if "limit_step" in ch.config:
            cls.LIMIT_STEP = int(ch.config["limit_step"])
            logger.debug("config: limit_step set to {}".format(cls.LIMIT_STEP))
        else:
            logger.debug("config: limit_step not set")

        if "interface_max_rate" in ch.config:
            cls.DEFAULT_MAX_RATE = int(ch.config["interface_max_rate"])
            logger.debug("config: interface_max_rate set to {}".format(cls.DEFAULT_MAX_RATE))
        else:
            logger.debug("config: interface_max_rate not set")

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
        r = requests.put("%s/v1.0/conf/switches/%016x/ovsdb_addr" % (QoSManager.CONTROLLER_BASEURL, self.__datapath.id),
                         data='"{}"'.format(QoSManager.OVSDB_ADDR),
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.log_rest_result(r)

    def set_queues(self):
        """Set queues on switches so that limits can be set on them."""
        # Extract port names and drop internal port named equivalently as the switch
        ports = sorted([port.name.decode('utf-8') for port in self.__datapath.ports.values()])[1:]
        self.__logger.debug("Ports to be configured: {}".format(ports))
        queue_limits = [QoSManager.DEFAULT_MAX_RATE] + [self.flows_limits[k][0] for k in self.flows_limits]
        for port in ports:
            r = requests.post("%s/qos/queue/%016x" % (QoSManager.CONTROLLER_BASEURL, self.__datapath.id),
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  "port_name": port, "type": "linux-htb", "max_rate": str(QoSManager.DEFAULT_MAX_RATE),
                                  "queues":
                                      [{"max_rate": str(limit)} for limit in queue_limits]
                              }))
            self.log_rest_result(r)

    def get_queues(self):
        """
        Get queues in the switch.

        WARNING: This request MUST be run some time after setting the OVSDB address to the controller.
        If it is run too soon, the controller responds with a failure.
        Calling this function right after setting the OVSDB address will result in occasional failures.
        """
        r = requests.get("%s/qos/queue/%016x" % (QoSManager.CONTROLLER_BASEURL, self.__datapath.id))
        self.log_rest_result(r)

    def adapt_queues(self, flowstats: Dict[FlowId, float]):
        modified = False
        unexploited_flows = [k for k, v in flowstats.items() if v < self.FLOWS_INIT_LIMITS[k][0]]
        full_flows = [k for k, v in flowstats.items() if v >= self.FLOWS_INIT_LIMITS[k][0]]
        self.__logger.debug("unexploited:\t%s\nfull:\t%s" % (unexploited_flows, full_flows))

        overall_gain = 0  # b/s which is available extra after rate reduction

        for k in unexploited_flows:
            load = flowstats[k]
            original_limit = self.FLOWS_INIT_LIMITS[k][0]
            bw_step = 0.1 * original_limit  # The granularity in which adaptation happens
            newlimit = max(ceil(load / bw_step) * bw_step, original_limit / 4)

            # Update the flows bandwidth limit only if _both the load and the new limit_ are further away from the
            # current limit than LIMIT_STEP. This dual condition is to avoid flapping of bandwidth settings when the
            # load is around an adaptation point and updating limits on flows with little resource assigned.
            if abs(load - self.get_current_limit(k)) >= QoSManager.LIMIT_STEP and \
                    self._update_limit(k,
                                       newlimit):  # This only runs if the first condition is true -> should be okay
                modified = True
            overall_gain += original_limit - self.get_current_limit(k)

        try:
            gain_per_flow = overall_gain / len(full_flows)
        except ZeroDivisionError:
            gain_per_flow = 0
        for k in full_flows:
            if self._update_limit(k, self.FLOWS_INIT_LIMITS[k][0] + gain_per_flow):
                modified = True
        if modified:
            self.set_queues()

    def set_rules(self):
        for k in self.flows_limits:
            r = requests.post("%s/qos/rules/%016x" % (QoSManager.CONTROLLER_BASEURL, self.__datapath.id),
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
        r = requests.get("%s/qos/rules/%016x" % (QoSManager.CONTROLLER_BASEURL, self.__datapath.id))
        self.log_rest_result(r)

    def get_current_limit(self, flow: FlowId) -> int:
        """
        Get current limit for a specific flow.

        :return: The current rate limit applied to `flow` in bits/s.
        """
        return self.flows_limits[flow][0]

    def get_initial_limit(self, flow: FlowId) -> int:
        """
        Get initial limit for a specific flow.

        :return: The initial rate limit applied to `flow` in bits/s.
        """
        return self.FLOWS_INIT_LIMITS[flow][0]

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
