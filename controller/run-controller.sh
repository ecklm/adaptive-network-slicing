#!/bin/bash

source .venv/bin/activate

set -v

ryu-manager --config-file  controller.cfg $@ \
	ryu.app.rest_qos \
	ryu.app.rest_conf_switch \
	qos_simple_switch_13.py \
	adapting_monitor_13.py \
	ryu.app.ofctl_rest \
	flow_cleaner_13.py
