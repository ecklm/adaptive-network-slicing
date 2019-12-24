#!/bin/bash

source .venv/bin/activate

set -v

ryu-manager ryu.app.rest_qos \
	ryu.app.rest_conf_switch \
	qos_simple_switch_13.py \
	adapting_monitor_13.py
