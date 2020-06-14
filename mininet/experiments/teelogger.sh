#!/bin/bash

if [ -z "$1" ]
then
	echo Please provide a log filename prefix!  >&2
	exit 1
fi

prefix="${1}-"
log_dir=experiment-logs

tee "${log_dir}/${prefix}last.log.csv" \
	"${log_dir}/${prefix}`date +"%F-%T"`.log.csv"
