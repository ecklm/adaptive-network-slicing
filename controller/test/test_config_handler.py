from copy import deepcopy

import pytest
from yaml.parser import ParserError

from config_handler import ConfigError, ConfigHandler

baseline = {
    'flows': [{'ipv4_dst': '10.0.0.1', 'udp_dst': 5009, 'base_ratelimit': 5000000},
              {'ipv4_dst': '10.0.0.8', 'udp_dst': 5002, 'base_ratelimit': 15000000},
              {'ipv4_dst': '10.0.0.1', 'udp_dst': 5003, 'base_ratelimit': 25000000}],
    'controller_baseurl': 'http://localhost:8080', 'ovsdb_addr': 'tcp:192.0.2.20:6632'
}


def test_config_handler_mandatory_only():
    ch = ConfigHandler("configs/mandatory_only.yml")
    assert baseline == ch.config


def test_config_handler_full():
    ch = ConfigHandler("configs/full.yml")

    full = deepcopy(baseline)
    full["time_step"] = 2
    full["limit_step"] = 2500000
    full["interface_max_rate"] = 5000000
    full["flowstat_window_size"] = 5

    assert full == ch.config


def test_config_handler_one_mandatory_missing():
    with pytest.raises(ConfigError):
        ConfigHandler("configs/one_mandatory_missing.yml")


def test_config_handler_multiple_mandatory_missing():
    with pytest.raises(ConfigError):
        ConfigHandler("configs/multiple_mandatory_missing.yml")


def test_config_handler_empty_config():
    with pytest.raises(ConfigError):
        ConfigHandler("configs/empty.yml")


def test_config_handler_yaml_syntax_error():
    with pytest.raises(ParserError):
        ConfigHandler("configs/syntax_error.yml")
