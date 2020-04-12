#!/bin/bash

source `dirname $0`/../common.sh

RAND_TIME_SUM=0
TIMES=()
BWS=()

while (( RAND_TIME_SUM < EXPERIMENT_LENGTH ))
do
	TIME=$((RANDOM % 80 + 10))
	BW=$((RANDOM % 28 + 2))

	(( RAND_TIME_SUM += TIME ))

	TIMES+=( $TIME )
	BWS+=( $BW )
done

echo "Total time: $RAND_TIME_SUM seconds."

for (( i=0; i<${#TIMES[@]}; i+=1 ))
do
	title "${BWS[$i]}Mbps for ${TIMES[$i]} seconds"
	iperf -c $UE2_IP -u -b ${BWS[$i]}M -t ${TIMES[$i]} -p $UE2_PORT
done
