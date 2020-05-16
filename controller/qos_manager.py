import json
import logging
from copy import deepcopy
from math import ceil
from typing import Tuple, Type

import requests
import ryu.lib.hub

from flow import *


class QoSManager:
    # The smallest difference in b/s that can result in rate limit changing in a queue. This
    # helps to perform hysteresis in the adapting logic
    LIMIT_STEP = 2 * 10 ** 6
    DEFAULT_MAX_RATE = -1  # Max rate to be set on a queue if not told otherwise.
    OVSDB_ADDR: str  # Address of the OVS database
    CONTROLLER_BASEURL: str  # Base URL where the controller can be reached.

    @classmethod
    def configure(cls, ch: config_handler.ConfigHandler) -> None:
        """
        Configure common class values based on the config file.

        :param ch: The config_handler object.
        """
        logger = logging.getLogger("qos_manager")

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

    def __init__(self, flows_with_init_limits: Dict[FlowId, int]):
        self.flows_limits: Dict[FlowId, Tuple[int, int]] = {}  # This will hold the actual values updated

        # Start from qnum = 1 so that the matches to the first rule does not get the same queue as non-matches
        flows_initlims_enum = enumerate(flows_with_init_limits, start=1)
        for qnum, k in flows_initlims_enum:
            self.flows_limits[k] = (flows_with_init_limits[k], qnum)
        self.FLOWS_INIT_LIMITS: Dict[FlowId, Tuple[int, int]] = \
            deepcopy(self.flows_limits)  # This does not change, it contains the values of the ideal, "customer" case

        self.__logger = logging.getLogger("qos_manager")

    def set_ovsdb_addr(self, dpid: int):
        """
        Set the address of the openvswitch database to the controller.

        This MUST be called once before sending configuration commands.
        :param dpid: datapath id to set OVSDB address for.
        """
        r = requests.put("%s/v1.0/conf/switches/%016x/ovsdb_addr" % (QoSManager.CONTROLLER_BASEURL, dpid),
                         data='"{}"'.format(QoSManager.OVSDB_ADDR),
                         headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.log_http_response(r)

    def set_queues(self, dpid: int = "all"):
        """
        Set queues on switches so that limits can be set on them.

        :param dpid: Optional numeric parameter to specify on which switch the queues should be set. Defaults to 'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        queue_limits = [QoSManager.DEFAULT_MAX_RATE] + [self.flows_limits[k][0] for k in self.flows_limits]
        try:
            r = requests.post("%s/qos/queue/%s" % (QoSManager.CONTROLLER_BASEURL, dpid),
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  # From doc: port_name is optional argument. If does not pass the port_name argument,
                                  # all ports are target for configuration.
                                  "type": "linux-htb", "max_rate": str(QoSManager.DEFAULT_MAX_RATE),
                                  "queues":
                                      [{"max_rate": str(limit)} for limit in queue_limits]
                              }))
            self.log_http_response(r)
        except requests.exceptions.ConnectionError as err:
            self.__logger.error("qos_manager: Queue setting has failed. {}".format(err))

    def get_queues(self, dpid: int = "all"):
        """
        Get queues in the switch.

        WARNING: This request MUST be run some time after setting the OVSDB address to the controller.
        If it is run too soon, the controller responds with a failure.
        Calling this function right after setting the OVSDB address will result in occasional failures.

        :param dpid: Optional numeric parameter to specify from which switch the queues should be retrieved. Defaults to
        'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        r = requests.get("%s/qos/queue/%s" % (QoSManager.CONTROLLER_BASEURL, dpid))
        self.log_http_response(r)

    def delete_queues(self, dpid: int = "all"):
        """
        Delete queues from the switch.

        :param dpid: Optional numeric parameter to specify on which switch the queues should be deleted. Defaults to
        'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        r = requests.delete("%s/qos/queue/%s" % (QoSManager.CONTROLLER_BASEURL, dpid))
        self.log_http_response(r)

    def _pre_adapt(self, flowstats: Dict[FlowId, float]) -> bool:
        """
        Calculate and locally update queue limits before sending updates to the switch.

        :return: Whether queue update needs to be sent to the switches or not.
        """
        modified = False
        unexploited_flows = [k for k, v in flowstats.items() if v < self.FLOWS_INIT_LIMITS[k][0]]
        full_flows = [k for k, v in flowstats.items() if v >= self.FLOWS_INIT_LIMITS[k][0]]
        self.__logger.debug("qosmanager:\n\tunexploited:\t%s\n\tfull:\t%s" % (unexploited_flows, full_flows))

        overall_gain = 0  # b/s which is available extra after rate reduction

        for flow in unexploited_flows:
            load = flowstats[flow]
            original_limit = self.FLOWS_INIT_LIMITS[flow][0]
            bw_step = 0.1 * original_limit  # The granularity in which adaptation happens
            newlimit = max(ceil(load / bw_step) * bw_step, original_limit / 4)

            # Update the flows bandwidth limit only if _both the load and the new limit_ are further away from the
            # current limit than LIMIT_STEP. This dual condition is to avoid flapping of bandwidth settings when the
            # load is around an adaptation point and updating limits on flows with little resource assigned.
            if abs(load - self.get_current_limit(flow)) >= QoSManager.LIMIT_STEP and \
                    self._update_limit(flow,
                                       newlimit):  # This only runs if the first condition is true -> should be okay
                modified = True
            overall_gain += original_limit - self.get_current_limit(flow)

        try:
            gain_per_flow = overall_gain / len(full_flows)
        except ZeroDivisionError:
            gain_per_flow = 0
        for flow in full_flows:
            if self._update_limit(flow, self.FLOWS_INIT_LIMITS[flow][0] + gain_per_flow):
                modified = True
        return modified

    def adapt_queues(self, flowstats: Dict[FlowId, float]):
        modified = self._pre_adapt(flowstats)
        if modified:
            self.set_queues()

    def set_rules(self, dpid: int = "all"):
        """
        Set rules for differentiated flows in switches.

        :param dpid: Optional numeric parameter to specify on which switch the rules should be set. Defaults to 'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        for k in self.flows_limits:
            r = requests.post("%s/qos/rules/%s" % (QoSManager.CONTROLLER_BASEURL, dpid),
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps({
                                  "match": {
                                      "nw_dst": k.ipv4_dst,
                                      "nw_proto": "UDP",
                                      "tp_dst": k.udp_dst,
                                  },
                                  "actions": {"queue": self.flows_limits[k][1]}
                              }))
            self.log_http_response(r)

    def get_rules(self, dpid: int = "all"):
        """
        Log rules already installed in the switch.

        WARNING: This call makes the switch send an OpenFlow statsReply message,
        which triggers every function subscribed to the ofp_event.EventOFPFlowStatsReply
        event.

        :param dpid: Optional numeric parameter to specify from which switch the rules should be retrieved. Defaults to
        'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        r = requests.get("%s/qos/rules/%s" % (QoSManager.CONTROLLER_BASEURL, dpid))
        self.log_http_response(r)

    def delete_rules(self, dpid: int = "all"):
        """
        Delete rules already installed in the switch.

        :param dpid: Optional numeric parameter to specify on which switch the rules should be deleted. Defaults to
        'all'.
        """
        if type(dpid) == int:
            dpid = "%016x" % dpid
        r = requests.delete("%s/qos/rules/%s" % (QoSManager.CONTROLLER_BASEURL, dpid),
                            headers={'Content-Type': 'application/json'},
                            data=json.dumps({"qos_id": "all"}))
        self.log_http_response(r)

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

    def log_http_response(self, r: requests.Response) -> None:
        if r.status_code >= 300 or \
                -1 != r.text.find("failure"):
            log = self.__logger.error
        else:
            log = self.__logger.debug
        try:
            log("{} - {}".format(r.status_code,
                                 json.dumps(r.json(), indent=4, sort_keys=True)))
        except ValueError:  # the response is not JSON
            log("{} - {}".format(r.status_code, r.text))


class ThreadedQoSManager(QoSManager):
    """Does the same thing as QoSManager, but wraps its functions to be thread safe."""

    def __init__(self, flows_with_init_limits: Dict[FlowId, int],
                 sem_cls: Type[ryu.lib.hub.Semaphore] = ryu.lib.hub.BoundedSemaphore,
                 blocking: bool = False):
        """
        Initialise a QoSManager object with the necessary semaphore settings.

        :param sem_cls: The class of the Semaphore to be used. Defaults to BoundedSemaphore by Ryu hub.
        :param blocking: Sets whether acquire() call should be blocking or not. In the non-blocking case, the respective
        function will simply be skipped. This can be overridden in the specific function calls.
        """
        super().__init__(flows_with_init_limits)
        self.__logger = logging.getLogger("threaded_qos_manager")

        self._resource_set_sem = sem_cls(1)
        self._adapt_sem = sem_cls(1)
        self._sem_blocking = blocking

    def set_queues(self, dpid: int = "all", blocking: bool = None):
        if blocking is None:
            blocking = self._sem_blocking
        sem_acquired = self._resource_set_sem.acquire(blocking)
        self.__logger.debug("threaded_qos_manager: _resource_set_sem.acquire = %s" % sem_acquired)
        if sem_acquired is False:
            self.__logger.debug("threaded_qos_manager: Skipping queue setting due to other pending operation.")
            return

        ret = super().set_queues(dpid)

        self._resource_set_sem.release(blocking)
        return ret

    def adapt_queues(self, flowstats: Dict[FlowId, float], blocking: bool = None):
        if blocking is None:
            blocking = self._sem_blocking
        sem_acquired = self._adapt_sem.acquire(blocking)
        self.__logger.debug("threaded_qos_manager: _adapt_sem.acquire = %s" % sem_acquired)
        if sem_acquired is False:
            self.__logger.debug("threaded_qos_manager: Skipping queue adaptation due to other pending operation.")
            return

        modified = self._pre_adapt(flowstats)
        if modified:
            self.set_queues(blocking=True)

        self._adapt_sem.release(blocking)
