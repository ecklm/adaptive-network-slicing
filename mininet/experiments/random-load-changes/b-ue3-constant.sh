#!/bin/bash

source `dirname $0`/../common.sh

iperf_cmd -c $UE3_IP -b ${DEFAULT_BW}M -t $EXPERIMENT_LENGTH -p $UE3_PORT
