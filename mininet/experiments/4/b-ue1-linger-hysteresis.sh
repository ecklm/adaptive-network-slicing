#!/bin/bash

source `dirname $0`/../common.sh

# NOTE: This script highly depends on the default setup of flow 1 where the
# maximum bandwidth is 5Mbps and where adaptation only happens on crossing half
# the bandwidth.

ADAPTATION_POINT=2500
t=$(( EXPERIMENT_LENGTH/6 ))

for i in {1..6}
do
	bw=$(( ADAPTATION_POINT + RANDOM % 300 - 150 )) # Kbps in this scenario

	title "${bw}Kbps for $t seconds"
	iperf_cmd -c $UE1_IP -b ${bw}K -t $t -p $UE1_PORT
done
