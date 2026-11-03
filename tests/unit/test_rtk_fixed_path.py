"""假数据注入：覆盖 GGA quality=4 / KSXT posqual=3 的有效放行路径。"""
import logging
from types import SimpleNamespace

import pytest

from edge.nodes.sensing.rtk_driver import run as driver_module
from edge.nodes.sensing.rtk_driver.run import RTKDriverNode


def sentence(body):
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"${body}*{checksum:02X}"


# KSXT: lon, lat, alt, heading, pitch, track, vel, roll, posqual, headingqual, hsats, msats
FIXED_KSXT = sentence(
    'KSXT,20261103120000.00,121.50000000,31.20000000,10.0000,123.45,0.00,123.45,0.000,0.00,3,3,20,20,,,,,,,,'
)
FLOAT_HEADING_KSXT = sentence(
    'KSXT,20261103120000.00,121.50000000,31.20000000,10.0000,123.45,0.00,123.45,0.000,0.00,3,2,20,20,,,,,,,,'
)
LOW_SATS_KSXT = sentence(
    'KSXT,20261103120000.00,121.50000000,31.20000000,10.0000,123.45,0.00,123.45,0.000,0.00,3,3,8,8,,,,,,,,'
)
# GGA quality 4 = RTK fixed；quality 1 = 单点
FIXED_GGA = sentence(
    'GNGGA,120000.00,3112.0000,N,12130.0000,E,4,20,0.6,10.0,M,0.0,M,,'
)
SINGLE_GGA = sentence(
    'GNGGA,120000.00,3112.0000,N,12130.0000,E,1,20,0.6,10.0,M,0.0,M,,'
)


def make_node(monkeypatch, line, **overrides):
    params = {
        'serial_port': '/dev/null',
        'serial_baudrate': 115200,
        'serial_timeout': 1.0,
        'use_network': False,
        'nmea_message': 'KSXT',
        'output_frequency': 10,
        'min_rtk_quality': 3,
        'min_satellites': 10,
        'heading_source': 'dual_antenna',
    }
    params.update(overrides)
    sent = []
    port = SimpleNamespace(send=lambda data: sent.append(data))
    sdk = SimpleNamespace(
        logger=logging.getLogger('test_rtk_fake'),
        get_param=lambda key, default=None: params.get(key, default),
        create_output_port=lambda name: port,
    )
    device = SimpleNamespace(
        is_connected=lambda: True,
        connect=lambda: True,
        read_line=lambda timeout=0.1: line,
        write=lambda cmd: True,
    )
    monkeypatch.setattr(driver_module, 'NodeFlowSDK', lambda **kwargs: sdk)
    monkeypatch.setattr(driver_module, 'create_interface', lambda config: device)
    node = RTKDriverNode()
    node.last_output_time = 0
    return node, sent


def test_fixed_ksxt_passes_and_outputs_full_packet(monkeypatch):
    node, sent = make_node(monkeypatch, FIXED_KSXT)
    node.loop()
    assert len(sent) == 1
    packet = sent[0]
    assert packet['rtk_quality'] == 3
    assert packet['rtk_status'] == 'FIXED'
    assert packet['heading_valid'] is True
    assert packet['heading'] == pytest.approx(123.45)
    assert packet['lat'] == pytest.approx(31.2)
    assert packet['lon'] == pytest.approx(121.5)
    assert packet['alt'] == pytest.approx(10.0)


def test_gga_quality_4_is_mapped_to_fixed_and_passes(monkeypatch):
    node, sent = make_node(monkeypatch, FIXED_GGA)
    node.loop()
    assert len(sent) == 1
    assert sent[0]['rtk_quality'] == 3
    assert sent[0]['rtk_status'] == 'FIXED'
    assert sent[0]['lat'] == pytest.approx(31.2)
    assert sent[0]['lon'] == pytest.approx(121.5)


def test_gga_quality_1_is_rejected(monkeypatch):
    node, sent = make_node(monkeypatch, SINGLE_GGA)
    node.loop()
    assert sent == []


def test_fixed_position_with_float_heading_keeps_position_but_no_heading(monkeypatch):
    node, sent = make_node(monkeypatch, FLOAT_HEADING_KSXT)
    node.loop()
    assert len(sent) == 1
    assert sent[0]['rtk_quality'] == 3
    assert sent[0]['heading'] is None
    assert sent[0]['heading_valid'] is False


def test_fixed_solution_with_low_satellites_is_rejected(monkeypatch):
    node, sent = make_node(monkeypatch, LOW_SATS_KSXT)
    node.loop()
    assert sent == []
