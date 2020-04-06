#!/usr/bin/env python2

from mininet.node import RemoteController
from mininet.net import Mininet
from mininet.log import setLogLevel
from mininet.cli import CLI
# from topologies import simplest
import topologies.simplest


if __name__ == '__main__':
    # Tell mininet to print useful information
    setLogLevel('info')
    "Create and test a simple network"
    topo = topologies.simplest.SimplestTopo()
    net = Mininet(topo, controller=RemoteController('c0', ip='192.0.2.1', port=6653))
    net.start()
    CLI(net)
    net.stop()
