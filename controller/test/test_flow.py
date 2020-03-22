import pytest

from flow import FlowId, FlowStat, FlowStatManager


def test_flowid_from_dict_correct():
    assert FlowId("192.0.2.1", 5009) == FlowId.from_dict({"ipv4_dst": "192.0.2.1", "udp_dst": 5009})


def test_flowid_from_dict_correct_unnecessary_data():
    assert FlowId("192.0.2.1", 5009) == FlowId.from_dict({"ipv4_dst": "192.0.2.1", "udp_dst": 5009, "dummy": 94})


def test_flowid_from_dict_incorrect_field():
    with pytest.raises(TypeError):
        FlowId.from_dict({"ipv4_dst": "192.0.2.1", "p": 5009})
