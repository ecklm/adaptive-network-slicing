#!/bin/bash

source .venv/bin/activate

set -v

ryu-manager ryu.app.rest_qos qos_simple_switch_13.py ryu.app.rest_conf_switch
