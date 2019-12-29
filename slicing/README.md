# Adapting network slicing using mininet and RYU

## Topology

```
  h1      h2
  |       |
  |50Mbps | 50Mbps
  |       |
  _________
 /________/|
 |        ||
 |   s1   ||
 |________|/
```

## Scenario

Given 3 flows:

- f1: DST:10.0.0.1:5001 -- 5Mbps
- f2: DST:10.0.0.1:5002 -- 15Mbps
- f3: DST:10.0.0.1:5003 -- 25Mbps

## Objective

When some of the flows are not using the maximum bandwidth available for them,
the other flows get a bit more than they are originally assigned

## Limitations and scenario

As this project is designed to be a demo to a university course, there are many
things hardwired into the code.

These specifications are mostly related to the topology and the specific flows.
These are namely:

- Use the reference Mininet VM available from their website for running the
  mininet part of this experiment.
- The mininet VM must have the following IP address: `192.0.2.20`
- The machine (supposedly the host machine) needs to have the following IP
  address: `192.0.2.1`
- The controller is set up to handle those specific three UDP flows, at the
  moment, using TCP or other flows are not supported.
