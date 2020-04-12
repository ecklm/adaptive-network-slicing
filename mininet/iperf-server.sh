#!/bin/bash

if [ -z $1 ]
then
	echo Please provide SERVER_PORT as command line argument! >&2
	exit 1
fi

SERVER_PORT=$1
iperf -s -u -i 1 -p $SERVER_PORT
