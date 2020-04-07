from mininet.topo import Topo


class ExperimentTopo(Topo):

    def build(self, *args, **params):
        # Add hosts, switches and links
        b = self.addHost('b', ip='10.0.0.1/8')
        c = self.addHost('c', ip='10.0.0.2/8')
        nb = self.addSwitch('nb', datapath='osvk', protocols='OpenFlow13', dpid='1')
        self.addLink(b, nb)
        self.addLink(c, nb)

        rb1 = self.addSwitch('rb1', datapath='osvk', protocols='OpenFlow13', dpid='2')
        rb2 = self.addSwitch('rb2', datapath='osvk', protocols='OpenFlow13', dpid='3')
        self.addLink(rb1, nb)
        self.addLink(rb2, nb)

        a1 = self.addSwitch('a1', datapath='osvk', protocols='OpenFlow13', dpid='4')
        self.addLink(a1, rb1)
        ue1 = self.addHost('ue1', ip='10.0.0.11/8')
        ue2 = self.addHost('ue2', ip='10.0.0.12/8')
        self.addLink(ue1, a1)
        self.addLink(ue2, a1)

        a2 = self.addSwitch('a2', datapath='osvk', protocols='OpenFlow13', dpid='5')
        self.addLink(a2, rb2)
        ue3 = self.addHost('ue3', ip='10.0.0.13/8')
        self.addLink(ue3, a2)


topos = {'experiment_topo': (lambda: ExperimentTopo())}
