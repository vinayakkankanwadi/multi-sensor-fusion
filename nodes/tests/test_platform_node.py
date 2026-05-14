"""platform-node probe — offline tests."""

from __future__ import annotations

import asyncio

from app.probes import platform_node as pn


ROUTER = {
    "id": "router",
    "type": "platform-node",
    "name": "Teltonika router",
    "host": "192.168.201.1",
    "services": ["ntp", "gps"],
}

NTP_OK = {"results": {"192.168.201.1": {
    "ok": True, "severity": "ok", "offset_s": 0.01, "rtt_s": 0.003,
    "error": None, "last_ok_at": 100.0}}}
NTP_WARN = {"results": {"192.168.201.1": {
    "ok": True, "severity": "warn", "offset_s": 1.0, "rtt_s": 0.003}}}
NTP_FAIL = {"results": {"192.168.201.1": {
    "ok": False, "severity": "fail", "error": "timeout"}}}

GPS_OK = {"ok": True, "source": "udp/0.0.0.0:8500 (from 192.168.201.1)",
          "fix_status": "valid", "satellites": 12, "age_s": 1.0}
GPS_WRONG_SOURCE = {"ok": True, "source": "udp/0.0.0.0:8500 (from 10.0.0.99)",
                    "fix_status": "valid", "satellites": 12, "age_s": 1.0}
GPS_BAD = {"ok": False, "source": "udp/0.0.0.0:8500 (from 192.168.201.1)",
           "error": "stale fix"}


def _run(entry, ntp, gps):
    return asyncio.run(pn.probe(entry, {"ntp_sources": ntp, "gps_fix": gps}))


def test_all_green_when_ntp_and_gps_ok():
    n = _run(ROUTER, NTP_OK, GPS_OK)
    assert n["ok"] is True
    assert n["severity"] == "ok"
    assert n["services"]["ntp"]["severity"] == "ok"
    assert n["services"]["gps"]["severity"] == "ok"


def test_warn_ntp_drags_to_warn():
    n = _run(ROUTER, NTP_WARN, GPS_OK)
    assert n["severity"] == "warn"


def test_fail_ntp_drags_to_fail():
    n = _run(ROUTER, NTP_FAIL, GPS_OK)
    assert n["severity"] == "fail"


def test_unknown_when_ntp_host_not_configured():
    n = _run(ROUTER, {"results": {}}, GPS_OK)
    assert n["services"]["ntp"]["severity"] == "unknown"
    assert n["severity"] == "unknown"


def test_gps_wrong_source_yields_unknown():
    n = _run(ROUTER, NTP_OK, GPS_WRONG_SOURCE)
    assert n["services"]["gps"]["severity"] == "unknown"


def test_gps_invalid_fix_from_right_host_fails():
    n = _run(ROUTER, NTP_OK, GPS_BAD)
    assert n["services"]["gps"]["severity"] == "fail"
    assert n["severity"] == "fail"


def test_missing_upstreams_become_unknown():
    n = _run(ROUTER, None, None)
    assert n["services"]["ntp"]["severity"] == "unknown"
    assert n["services"]["gps"]["severity"] == "unknown"
    assert n["severity"] == "unknown"


def test_no_services_means_unknown():
    cfg = {"id": "x", "type": "platform-node", "name": "x",
           "host": "0.0.0.0", "services": []}
    n = _run(cfg, NTP_OK, GPS_OK)
    assert n["severity"] == "unknown"
    assert n["services"] == {}
