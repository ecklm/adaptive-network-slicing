#!/bin/bash

source `dirname $0`/../common.sh

iperf -c $UE2_IP -u -b 30M -t $EXPERIMENT_LENGTH -p $UE2_PORT
