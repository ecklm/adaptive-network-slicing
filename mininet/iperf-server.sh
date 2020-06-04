#!/bin/bash

if [ -z $1 ]
then
	echo Please provide SERVER_PORT as command line argument! >&2
	exit 1
fi

source `dirname $0`/experiments/common.sh

SERVER_PORT=$1
iperf_cmd -s -p $SERVER_PORT
