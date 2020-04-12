#!/bin/bash

source `dirname $0`/../common.sh

for bw in 23 21 19 17 15 13 11 9 7 5 2 \
          5 7 11 13 15 17 19 21 23
do
	title "${bw}Mbps for 30 seconds"
	iperf -c $UE3_IP -u -b ${bw}M -t 30 -p $UE3_PORT
done
