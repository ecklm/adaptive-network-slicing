#!/bin/bash

source `dirname $0`/../common.sh

iperf_cmd -c $UE2_IP -b ${DEFAULT_BW}M -t $EXPERIMENT_LENGTH -p $UE2_PORT
