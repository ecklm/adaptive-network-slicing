#!/bin/bash

source `dirname $0`/../common.sh

title "${DEFAULT_BW}Mbps for 90 seconds"
iperf_cmd -c 10.0.0.2 -b ${DEFAULT_BW}M -t 90 -p 5001
