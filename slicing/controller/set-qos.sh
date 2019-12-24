#!/bin/bash

set -v

# OVS runs on mininet VM
curl -X PUT -d '"tcp:192.0.2.20:6632"' \
	http://localhost:8080/v1.0/conf/switches/0000000000000001/ovsdb_addr | jq .

# Creating diferent QoS queues
curl -X POST -d '{"port_name": "s1-eth1", "type": "linux-htb", "max_rate": "50000000",
	"queues":
		[{"max_rate": "5000000"}, {"max_rate": "15000000"}, {"max_rate": "25000000"}]
	}' \
	http://localhost:8080/qos/queue/0000000000000001 | jq .

# Set the differentiated flow to the differentiated queue
curl -X POST -d '{"match": {"nw_dst": "10.0.0.1", "nw_proto": "UDP", "tp_dst":
	  "5001"}, "actions":{"queue": "0"}}' \
	http://localhost:8080/qos/rules/0000000000000001 | jq .
curl -X POST -d '{"match": {"nw_dst": "10.0.0.1", "nw_proto": "UDP", "tp_dst":
	  "5002"}, "actions":{"queue": "1"}}' \
	http://localhost:8080/qos/rules/0000000000000001 | jq .
curl -X POST -d '{"match": {"nw_dst": "10.0.0.1", "nw_proto": "UDP", "tp_dst":
	  "5003"}, "actions":{"queue": "2"}}' \
	http://localhost:8080/qos/rules/0000000000000001 | jq .

# Verify settings
curl -X GET http://localhost:8080/qos/rules/0000000000000001 | jq .
