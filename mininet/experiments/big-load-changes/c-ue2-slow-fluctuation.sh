#!/bin/bash

source `dirname $0`/../common.sh

for bw in 40 21 5 17 30 2 7
do
	title "${bw}Mbps for 90 seconds"
	iperf_cmd -c $UE2_IP -b ${bw}M -t 90 -p $UE2_PORT
done
title "7Mbps for 60 seconds"
iperf_cmd -c $UE2_IP -b 7M -t 60 -p $UE2_PORT
