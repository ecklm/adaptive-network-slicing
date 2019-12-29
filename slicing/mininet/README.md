# Experiment

This directory should be mounted or copied into the reference mininet VM
available [here](https://github.com/mininet/mininet/wiki/Mininet-VM-Images).

Then to run the setup you should run `setup-mininet.sh`. The experimentation
part is manual to make the demo interactive. The initial commands are described
in `commands-to-run`, they should be run in three different terminals on `h1` and
`h2` each.

Changing the `iperf` client commands and looking at the controller logs should
reveal the working adaptation functionality. For example if you start all
clients to send 30Mb/s traffic, all of the servers should show the assigned
bandwidths. Then if you change the bw for the second client (port 5002) to
5Mb/s, you should see after about a minute that the rest of the flows manage to
transmit more data than the originally assigned value. This is the objective of
adaptive slicing.
