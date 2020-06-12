#!/bin/bash

source `dirname $0`/../common.sh

dst=$1  # Textual name of the destination host
case $dst in
	ue1)
		IP=$UE1_IP
		PORT=$UE1_PORT
		;;
	ue2)
		IP=$UE2_IP
		PORT=$UE2_PORT
		;;
	ue3)
		IP=$UE3_IP
		PORT=$UE3_PORT
		;;
	*)
		echo "Please specify destination host (ue1, ue2, ue3)" >&2
		exit 1
esac

iperf_cmd -c $IP -b ${DEFAULT_BW}M -t $EXPERIMENT_LENGTH -p $PORT
