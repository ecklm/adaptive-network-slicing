#!/bin/bash

source `dirname $0`/../common.sh

iperf -c $UE1_IP -u -b 30M -t $EXPERIMENT_LENGTH -p $UE1_PORT
