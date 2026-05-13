"""Converter tests — exercise each content type with a known input.

The proto bindings under ui/sapient_msg/ are generated at docker
build time. To run these tests on the host: have the ui container
running (so the package can be reused), or generate sapient_msg/ first via
`deprecated/compat-baseline/edge-sim/generate_proto.sh`.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Skip cleanly if proto bindings aren't generated locally.
THIS = Path(__file__).resolve().parent
HOST_PROTO = THIS.parent.parent / "deprecated" / "compat-baseline" / "edge-sim" / "sapient_msg"
if not HOST_PROTO.exists():
    pytest.skip("sapient_msg bindings not present locally", allow_module_level=True)

sys.path.insert(0, str(HOST_PROTO.parent))    # deprecated/compat-baseline/edge-sim/

from sapient_msg.bsi_flex_335_v2_0 import (  # noqa: E402
    location_pb2 as _loc,
    registration_pb2 as _reg,
    sapient_message_pb2 as _msg,
    status_report_pb2 as _stat,
)

# Add the converter package to the path
sys.path.insert(0, str(THIS.parent.parent))
import sapient_to_cot as cvt  # noqa: E402

NODE = "11111111-1111-1111-1111-111111111111"


def _envelope() -> _msg.SapientMessage:
    m = _msg.SapientMessage()
    m.timestamp.GetCurrentTime()
    m.node_id = NODE
    return m


def test_registration_uses_node_type_to_pick_cot_type():
    m = _envelope()
    nd = m.registration.node_definition.add()
    nd.node_type = _reg.Registration.NODE_TYPE_RADAR
    m.registration.short_name = "test-radar"
    out = cvt.convert(m, fallback_lat=-27.5, fallback_lon=153.0, fallback_alt=10)
    assert out is not None
    root = ET.fromstring(out.split(b"?>", 1)[1])
    assert root.attrib["uid"] == NODE
    assert root.attrib["type"] == "a-f-G-E-S-R"   # radar sensor
    assert root.find("./detail/contact").attrib["callsign"] == "test-radar"


def test_registration_returns_none_without_position():
    m = _envelope()
    nd = m.registration.node_definition.add()
    nd.node_type = _reg.Registration.NODE_TYPE_RADAR
    assert cvt.convert(m) is None


def test_detection_report_uses_location_when_present():
    m = _envelope()
    d = m.detection_report
    d.report_id = "01HABCDEFGHJKMNPQRSTVWXYZ0"
    d.object_id = "01HABCDEFGHJKMNPQRSTVWXY11"
    d.location.x = -27.4698
    d.location.y = 153.0251
    d.location.z = 27.0
    d.location.coordinate_system = _loc.LocationCoordinateSystem.LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M
    d.location.datum = _loc.LocationDatum.LOCATION_DATUM_WGS84_E
    out = cvt.convert(m)
    assert out is not None
    root = ET.fromstring(out.split(b"?>", 1)[1])
    assert root.attrib["type"] == "a-u-G"   # detection default
    pt = root.find("./point")
    assert float(pt.attrib["lat"]) == pytest.approx(-27.4698)
    assert float(pt.attrib["lon"]) == pytest.approx(153.0251)


def test_status_report_uses_node_location_when_present():
    m = _envelope()
    s = m.status_report
    s.report_id = "01HABCDEFGHJKMNPQRSTVWXYZ0"
    s.system = 1; s.info = 1; s.mode = "default"
    s.node_location.x = -27.5; s.node_location.y = 153.1; s.node_location.z = 5.0
    s.node_location.coordinate_system = _loc.LocationCoordinateSystem.LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M
    s.node_location.datum = _loc.LocationDatum.LOCATION_DATUM_WGS84_E
    out = cvt.convert(m)
    assert out is not None
    root = ET.fromstring(out.split(b"?>", 1)[1])
    pt = root.find("./point")
    assert float(pt.attrib["lat"]) == pytest.approx(-27.5)


def test_alert_returns_hostile_default_type_when_position_present():
    m = _envelope()
    a = m.alert
    a.alert_id = "01HABCDEFGHJKMNPQRSTVWXYZ0"
    a.location.x = -27.0; a.location.y = 153.0; a.location.z = 0.0
    a.location.coordinate_system = _loc.LocationCoordinateSystem.LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M
    a.location.datum = _loc.LocationDatum.LOCATION_DATUM_WGS84_E
    out = cvt.convert(m)
    assert out is not None
    root = ET.fromstring(out.split(b"?>", 1)[1])
    assert root.attrib["type"] == "a-h-G"


def test_unsupported_content_returns_none():
    m = _envelope()
    m.error.packet = b"\x00"
    m.error.error_message.append("x")
    assert cvt.convert(m) is None
