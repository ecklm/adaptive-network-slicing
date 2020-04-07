#!/usr/bin/env python2

from mininet.node import RemoteController
from mininet.net import Mininet
from mininet.log import setLogLevel
from mininet.cli import CLI
import topologies.experiment


if __name__ == '__main__':
    # Tell mininet to print useful information
    setLogLevel('info')
    topo = topologies.experiment.ExperimentTopo()
    net = Mininet(topo, controller=RemoteController('c0', ip='192.0.2.1', port=6653))
    net.start()
    CLI(net)
    net.stop()
