A_IP=10.0.0.1
B_IP=10.0.0.2
UE1_IP=10.0.0.11; UE1_PORT=5001
UE2_IP=10.0.0.12; UE2_PORT=5002
UE3_IP=10.0.0.13; UE3_PORT=5003

EXPERIMENT_LENGTH=600 # Number of seconds experiments should last.

function title {
	echo ========== $1 ==========
}

function project_csv {
	# Output:
	# Unix time stamp, Local IP, Local Port, Remote IP, Remote Port, Report interval, Bandwidth (bps)
	while read line
	do
		printf "`date +'%s'`,"
		echo "$line" | cut -d, -f2-5,7,9
	done
}

function iperf_cmd {
	iperf -u -i 1 --reportstyle C $@ | project_csv
}

# Record time for both the beginning and the end of each experiment
function DATE_CMD {
	date --utc +"%F %T = %s"
}
trap DATE_CMD EXIT
DATE_CMD
