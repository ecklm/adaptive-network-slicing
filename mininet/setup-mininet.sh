#!/bin/bash

sudo mn --custom mn-slicing.py --topo slicingtopo \
	--mac \
	--controller remote,ip=192.0.2.1,port=6653
