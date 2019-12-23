from mininet.topo import Topo

class SlicingTopo(Topo):
    """Custom topology for network slicing

       h1 --- s1 --- h2

    Designed to be a specific base for the experiment.
    """

    def __init__( self ):
        "Create custom topo."

        # Initialize topology
        Topo.__init__( self )

        # Add hosts and switches
        h1 = self.addHost( 'h1' )
        h2 = self.addHost( 'h2' )
        s1 = self.addSwitch( 's1' )

        # Add links
        self.addLink(h1, s1)
        self.addLink(h2, s1)


topos = { 'slicingtopo': ( lambda: SlicingTopo() ) }
