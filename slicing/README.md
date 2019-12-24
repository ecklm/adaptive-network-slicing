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

