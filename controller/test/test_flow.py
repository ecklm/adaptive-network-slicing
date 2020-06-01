import pytest

import config_handler
from flow import FlowId, FlowStat, FlowStatManager


# ====== FlowId tests ======
def test_flowid_from_dict_correct():
    assert FlowId("192.0.2.1", 5009) == FlowId.from_dict({"ipv4_dst": "192.0.2.1", "udp_dst": 5009})


def test_flowid_from_dict_correct_unnecessary_data():
    assert FlowId("192.0.2.1", 5009) == FlowId.from_dict({"ipv4_dst": "192.0.2.1", "udp_dst": 5009, "dummy": 94})


def test_flowid_from_dict_incorrect_field():
    with pytest.raises(TypeError):
        FlowId.from_dict({"ipv4_dst": "192.0.2.1", "p": 5009})


# def test_flowid_udp_dst_type_fix():
#     assert FlowId("192.0.2.1", 5009) == FlowId("192.0.2.1", "5009")
#
#
# def test_flowid_udp_dst_type_check():
#     with pytest.raises(TypeError):
#         FlowId("192.0.2.1", [1, 3, 5, 7])


# ====== FlowStat tests ======
ch = config_handler.ConfigHandler("configs/full.yml")
FlowStat.configure(ch)


# To be uncommented when there are fixed config files for testing
# def test_flowstat_config_success():
#     assert FlowStat.WINDOW_SIZE == 6


def test_flowstat_get_empty():
    f = FlowStat()
    assert f.get_avg() == 0


def test_flowstat_put_negative_number():
    f = FlowStat()
    with pytest.raises(ValueError):
        f.put(-4)


def test_flowstat_put_out_of_order_number():
    f = FlowStat()
    with pytest.raises(ValueError):
        f.put(1)
        f.put(5)
        f.put(4)


def test_flowstat_get_one():
    f = FlowStat()
    f.put(5)
    assert f.get_avg() == 5


def test_flowstat_get_avg():
    f = FlowStat()
    for x in [1, 3, 5, 7]:
        f.put(x)
    assert f.get_avg() == 2


def test_flowstat_get_avg_good_prefix():
    f = FlowStat()
    for x in [1, 3, 5, 7]:
        f.put(x)
    assert f.get_avg('K') == 2 / 1000 and f.get_avg('M') == 2 / 1000000 and f.get_avg('G') == 2 / 1000000000


def test_flowstat_get_avg_bad_prefix():
    f = FlowStat()
    for x in [1, 3, 5, 7]:
        f.put(x)
    with pytest.raises(KeyError):
        f.get_avg('F')


def test_flowstat_get_avg_speed():
    f = FlowStat()
    timestamp = 0
    for x in [1, 3, 5, 7]:
        f.put(x, timestamp)
        timestamp += 5
    assert f.get_avg_speed() == 0.4


def test_flowstat_get_avg_speed_bps():
    f = FlowStat()
    timestamp = 0
    for x in [1, 3, 5, 7]:
        f.put(x, timestamp)
        timestamp += 5
    assert f.get_avg_speed_bps() == 0.4 * 8


# ====== FlowStatManager tests ======

f1 = FlowId("192.0.2.1", 5001)
f2 = FlowId("192.0.2.1", 5002)


def test_flowstatmanager_get_avg_two_flows():
    fm = FlowStatManager()
    for x in [1, 3, 5, 7]:
        fm.put(f1, x)
    for x in [6, 13, 25, 27]:
        fm.put(f2, x)
    assert fm.get_avg(f1) == 2 and fm.get_avg(f2) == 7


def test_flowstatmanager_get_unmanaged_flow():
    fm = FlowStatManager()
    with pytest.raises(KeyError):
        fm.get_avg(f1)


def test_export_avg_speeds():
    fm = FlowStatManager()
    timestamp = 0
    for x in [1, 3, 5, 7]:
        fm.put(f1, x, timestamp)
        timestamp += 5
    for x in [6, 13, 25, 27]:
        fm.put(f2, x, timestamp)
        timestamp += 5
    assert fm.export_avg_speeds() == {f1: 0.4, f2: 1.4}
