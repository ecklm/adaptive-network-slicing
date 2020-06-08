from mininet.topo import Topo


class OutlierTopo(Topo):
    """
    Topology to demonstrate that the controller is able to manage different topologies (aka. topology independency).

       h1 --- s1 --- s2 --- h2

    Designed to be a specific base for the experiment.
    """

    def build(self, *args, **params):
        "Create custom topo."

        # Add hosts and switches
        h1 = self.addHost('h1')
        s1 = self.addSwitch('s1', datapath='osvk', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', datapath='osvk', protocols='OpenFlow13')
        h2 = self.addHost('h2')

        # Add links
        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(s2, h2)


topos = {'outlier_topo': (lambda: OutlierTopo())}
