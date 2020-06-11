#!/bin/bash

source `dirname $0`/../common.sh

bw=30
title "${bw}Mbps for 90 seconds"
iperf_cmd -c 10.0.0.2 -b ${bw}M -t 90 -p 5001
