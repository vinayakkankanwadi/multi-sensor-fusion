"""Aggregator unit tests — offline, no upstream services."""

from __future__ import annotations

from app.aggregator import aggregate


ROUTER = {
    "id": "router",
    "name": "Teltonika router",
    "host": "192.168.201.1",
    "services": ["ntp", "gps"],
    "description": "test router",
}

NTP_OK = {"results": {"192.168.201.1": {
    "ok": True, "severity": "ok", "offset_s": 0.01, "rtt_s": 0.003,
    "error": None, "last_ok_at": 100.0}}}
NTP_WARN = {"results": {"192.168.201.1": {
    "ok": True, "severity": "warn", "offset_s": 1.0, "rtt_s": 0.003,
    "error": None}}}
NTP_FAIL = {"results": {"192.168.201.1": {
    "ok": False, "severity": "fail", "error": "timeout"}}}

GPS_OK = {"ok": True, "source": "udp/0.0.0.0:8500 (from 192.168.201.1)",
          "fix_status": "valid", "satellites": 12, "age_s": 1.0}
GPS_WRONG_SOURCE = {"ok": True, "source": "udp/0.0.0.0:8500 (from 10.0.0.99)",
                    "fix_status": "valid", "satellites": 12, "age_s": 1.0}
GPS_BAD = {"ok": False, "source": "udp/0.0.0.0:8500 (from 192.168.201.1)",
           "error": "stale fix"}


def test_router_all_green_when_ntp_and_gps_ok():
    n = aggregate(ROUTER, NTP_OK, GPS_OK)
    assert n["ok"] is True
    assert n["severity"] == "ok"
    assert n["services"]["ntp"]["severity"] == "ok"
    assert n["services"]["gps"]["severity"] == "ok"


def test_warn_ntp_drags_node_to_warn():
    n = aggregate(ROUTER, NTP_WARN, GPS_OK)
    assert n["severity"] == "warn"
    assert n["ok"] is False


def test_fail_ntp_drags_node_to_fail():
    n = aggregate(ROUTER, NTP_FAIL, GPS_OK)
    assert n["severity"] == "fail"


def test_unknown_when_ntp_host_not_configured():
    n = aggregate(ROUTER, {"results": {}}, GPS_OK)  # router not in NTP sources
    assert n["services"]["ntp"]["severity"] == "unknown"
    assert "not in msf-ntp" in n["services"]["ntp"]["error"]
    assert n["severity"] == "unknown"  # unknown is worse than ok


def test_gps_from_different_host_yields_unknown_not_fail():
    n = aggregate(ROUTER, NTP_OK, GPS_WRONG_SOURCE)
    assert n["services"]["gps"]["severity"] == "unknown"
    assert "10.0.0.99" in n["services"]["gps"]["error"]


def test_gps_invalid_fix_from_right_host_yields_fail():
    n = aggregate(ROUTER, NTP_OK, GPS_BAD)
    assert n["services"]["gps"]["severity"] == "fail"
    assert n["severity"] == "fail"


def test_missing_upstreams_become_unknown_not_crash():
    n = aggregate(ROUTER, None, None)
    assert n["services"]["ntp"]["severity"] == "unknown"
    assert n["services"]["gps"]["severity"] == "unknown"
    assert n["severity"] == "unknown"


def test_node_with_no_services_has_unknown_severity():
    cfg = {"id": "x", "name": "x", "host": "0.0.0.0", "services": []}
    n = aggregate(cfg, NTP_OK, GPS_OK)
    assert n["severity"] == "unknown"
    assert n["services"] == {}
