import requests
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3


class FlowCleaner13(app_manager.RyuApp):
    """
    This application is only responsible for cleaning up flow entries from the switches before the controller exits.

    This is a separate application as the scope of deletion is broader than any specific application's.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def close(self):
        for dpid in self.__datapaths:
            r = requests.delete("http://localhost:8080/stats/flowentry/clear/%d" % dpid)
            if r.status_code >= 200 and r.status_code < 300:
                self.logger.info("flow_cleaner: Deleted all flow entries from %016x" % dpid)
            else:
                self.logger.error("flow_cleaner: Failed to deleted all flow entries from %016x. Reason: %s" %
                                  (dpid, r.text))

    def __init__(self, *args, **kwargs):
        super(FlowCleaner13, self).__init__(*args, **kwargs)
        self.__datapaths = set()

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER])
    def _register_datapath(self, ev):
        if ev.datapath.id is None:
            return
        self.logger.debug('flow_cleaner: register datapath: %016x', ev.datapath.id)
        self.__datapaths.add(ev.datapath.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [DEAD_DISPATCHER])
    def _unregister_datapath(self, ev):
        if ev.datapath.id is None:
            return
        self.logger.debug('flow_cleaner: unregister datapath: %016x', ev.datapath.id)
        self.__datapaths.remove(ev.datapath.id)
