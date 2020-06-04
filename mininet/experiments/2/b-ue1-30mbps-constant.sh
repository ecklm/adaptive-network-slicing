#!/bin/bash

source `dirname $0`/../common.sh

iperf_cmd -c $UE1_IP -b 30M -t $EXPERIMENT_LENGTH -p $UE1_PORT
