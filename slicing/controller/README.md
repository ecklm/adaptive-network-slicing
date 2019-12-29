# Controller implementation

The network application uses the RYU controller and the QoS switch to achieve
the adaptive slicing. The concept is to differentiate between three flows and
assign them to different queues. This is enough to demonstrate the idea.

The application that is responsible for adaptivity is in
`adaptive_monitor_13.py` which maintains some statistics and uses REST API calls
to set and update QoS parameters in the `qos_simple_switch_13.py` app. The basis
of the decision is the number of bytes matched against specific flows. If this
averages more than half of the assigned bandwidth, the full bandwidth stays
assigned. If it decreases below half of the assigned value, the bandwidths gets
reset and the gained extra available bandwidth is distributed equally to those
flows which use more than half of their assigned bandwidths.

## Running the controller

To run the controller, I recommend setting up a virtual environment with Python3
and installing the python dependencies.  Then you can use the
`run-controller.sh` script.

**Note:** Initialising the QoS settings is a bit problematic. It may happen that
it fails at the queue setting step claiming missing OVS switch. It is
time-dependent so a few restarts must be enough to start it correctly. If you
don't see the JSON with the error, there is no problem.
