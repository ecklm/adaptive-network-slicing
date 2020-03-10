#!/bin/bash

sudo mn --custom topologies/simplest.py --topo simplest_topo \
	--mac \
	--controller remote,ip=192.0.2.1,port=6653
