from dataclasses import dataclass
from typing import Dict

import config_handler


@dataclass(frozen=True)
class FlowId:
    ipv4_dst: str
    udp_dst: int

    @classmethod
    def from_dict(cls, d: Dict[str, int]):
        """
        Create a FlowId object out of a dictionary, using the properly named fields.

        In case the dictionary does not have the appropriate fields, a TypeError
        exception is raised.

        :param d: The dictionary to parse.
        """
        try:
            return FlowId(d["ipv4_dst"], d["udp_dst"])
        except KeyError as ex:
            raise TypeError("The given dict is not a proper FlowId, {} is missing.".format(ex)) from ex


class FlowStat:
    WINDOW_SIZE = 10  # The number of data stored for statistical calculations
    SCALING_PREFIXES = {'K': 1 / 1000, 'M': 1 / 1000000, 'G': 1 / 1000000000, None: 1}

    @classmethod
    def configure(cls, ch: config_handler.ConfigHandler, logger) -> None:
        """
        Configure common class values based on the config file.

        :param ch: The config_handler object.
        :param logger: Logger to log messages to.
        """
        # Optional fields
        if "flowstat_window_size" in ch.config:
            cls.WINDOW_SIZE = int(ch.config["flowstat_window_size"])
            logger.debug("config: flowstat_window_size set to {}".format(cls.WINDOW_SIZE))
        else:
            logger.debug("config: flowstat_window_size not set")

    def __init__(self, time_step: int):
        """:param time_step: The number of seconds between two measurements."""
        self.data = []
        self.time_step = time_step

    def put(self, val: int):
        """
        Put data in the list for calculating statistics.

        :param val: Must be a positive integer and greater than or equal to the last value.
        :raises ValueError: If `val` is semantically incorrect.
        """
        if val < 0:
            raise ValueError("Values in need to be positive. Got {}".format(val))
        try:
            if val < self.data[-1]:
                raise ValueError("Data must show monotonic increase. Passed data is smaller than last one. []".format(
                    [self.data[-1], val])
                )
        except IndexError:
            pass
        if len(self.data) < FlowStat.WINDOW_SIZE:
            self.data.append(val)
        else:
            self.data = self.data[1:] + [val]

    def get_avg(self, prefix: str = None) -> float:
        """
        Get the average number of bytes per measurement during the last `WINDOW_SIZE` number of measurements.

        :param prefix: A prefix to scale the result with. See possible values in `FlowStat.SCALING_PREFIXES`.
        """
        if len(self.data) == 0:
            return 0
        elif len(self.data) == 1:
            # This number will not necessarily make sense, but at least it may prevent the QoS manager from decreasing
            # the limits for all flows at the first measurement
            return self.data[0]
        else:
            return (self.data[-1] - self.data[0]) * FlowStat.SCALING_PREFIXES[prefix] / float(len(self.data) - 1)

    def get_avg_speed(self, prefix: str = None) -> float:
        """
        Get the average throughput of the Flow during the last `WINDOW_SIZE` number of measurements in **Bytes/s**.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        """
        return self.get_avg(prefix) / float(self.time_step)

    def get_avg_speed_bps(self, prefix: str = None) -> float:
        """
        Get The average throughput of the Flow during the last `WINDOW_SIZE` number of measurements in **bits/s**.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        """
        return self.get_avg_speed(prefix) * 8


class FlowStatManager:
    def __init__(self, time_step):
        self.stats: Dict[FlowId, FlowStat] = {}
        self.time_step = time_step

    def put(self, flow: FlowId, val: int) -> None:
        """
        Add a new record to the specified flow's stats.

        :param flow: The identifier of the Flow.
        :param val: The measurement value.
        """
        try:
            self.stats[flow].put(val)
        except KeyError:
            self.stats[flow] = FlowStat(self.time_step)
            self.stats[flow].put(val)

    def get_avg(self, flow: FlowId, prefix: str = None) -> float:
        """
        Get the result of `FlowStat.get_avg` for the given flow.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        """
        return self.stats[flow].get_avg(prefix)  # Let the KeyError exception arise if any

    def get_avg_speed(self, flow: FlowId, prefix: str = None) -> float:
        """
        Get the result of `FlowStat.get_avg_speed` for the given flow.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        """
        return self.stats[flow].get_avg_speed(prefix)

    def get_avg_speed_bps(self, flow: FlowId, prefix: str = None) -> float:
        """
        Get the result of `FlowStat.get_avg_bps` for the given flow.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        """
        return self.stats[flow].get_avg_speed_bps(prefix)

    def export_avg_speeds(self, prefix: str = None) -> Dict[FlowId, float]:
        """
        Export the FlowStats associated to FlowIds.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        :return: A Dict of {FlowId, avg_speed}.
        """
        return {k: v.get_avg_speed(prefix) for (k, v) in self.stats.items()}

    def export_avg_speeds_bps(self, prefix: str = None) -> Dict[FlowId, float]:
        """
        Export the FlowStats associated to flowIds.

        :param prefix: See `FlowStat.get_avg` parameter documentation.
        :return: A Dict of {FlowId, avg_speed_bps}.
        """
        return {k: v.get_avg_speed_bps(prefix) for (k, v) in self.stats.items()}
