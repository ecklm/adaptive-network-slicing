#!/bin/bash

sudo mn --mac --switch ovsk,protocols=OpenFlow13 \
	--controller remote,ip=192.0.2.1,port=6653
