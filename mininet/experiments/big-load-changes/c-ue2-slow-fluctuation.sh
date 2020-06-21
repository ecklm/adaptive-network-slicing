#!/bin/bash

source `dirname $0`/../common.sh

t=90

for bw in 40 2 17 2
do
	title "${bw}Mbps for ${t} seconds"
	iperf_cmd -c $UE2_IP -b ${bw}M -t ${t} -p $UE2_PORT
done
