#!/bin/bash

source `dirname $0`/../common.sh

iperf -c $UE3_IP -u -b 30M -t $EXPERIMENT_LENGTH -p $UE3_PORT
