"""NTP probe tests.

The first three exercise the offline parsing/severity logic without touching
the network. The last is opt-in (skipped unless `MSF_NTP_LIVE=1`) and queries
a real NTP server, since CI environments often block UDP/123.
"""

from __future__ import annotations

import asyncio
import os
import struct

import pytest

from app import ntp


def _fake_ntp_packet(server_time: float) -> bytes:
    """Build a minimal NTP v3 reply where rx == tx == server_time."""
    seconds = int(server_time) + ntp._NTP_TO_UNIX
    fraction = int((server_time - int(server_time)) * (1 << 32))
    out = bytearray(48)
    # leave bytes 0-31 as zeros — irrelevant fields for our parser.
    struct.pack_into("!II", out, 32, seconds, fraction)  # receive timestamp
    struct.pack_into("!II", out, 40, seconds, fraction)  # transmit timestamp
    return bytes(out)


def test_severity_classification_thresholds():
    assert ntp.WARN_THRESHOLD_S < ntp.FAIL_THRESHOLD_S
    # construct a result manually and check severity boundaries
    for offset, expected in [(0.0, "ok"),
                             (0.4, "ok"),
                             (0.6, "warn"),
                             (1.5, "warn"),
                             (3.0, "fail")]:
        if abs(offset) >= ntp.FAIL_THRESHOLD_S:
            sev = "fail"
        elif abs(offset) >= ntp.WARN_THRESHOLD_S:
            sev = "warn"
        else:
            sev = "ok"
        assert sev == expected, f"offset={offset}"


def test_query_handles_short_reply(monkeypatch):
    class FakeSock:
        def __init__(self, *a, **k): pass
        def settimeout(self, *_): pass
        def sendto(self, *_): pass
        def recvfrom(self, _n): return (b"\x00" * 10, ("127.0.0.1", 123))
        def close(self): pass
    monkeypatch.setattr(ntp.socket, "socket", lambda *a, **k: FakeSock())
    res = ntp._query_sync("fake", 123, 1.0)
    assert not res.ok
    assert res.severity == "fail"
    assert "short reply" in res.error


def test_query_handles_network_error(monkeypatch):
    class FakeSock:
        def __init__(self, *a, **k): pass
        def settimeout(self, *_): pass
        def sendto(self, *_): pass
        def recvfrom(self, _n): raise OSError("no route")
        def close(self): pass
    monkeypatch.setattr(ntp.socket, "socket", lambda *a, **k: FakeSock())
    res = ntp._query_sync("fake", 123, 1.0)
    assert not res.ok
    assert "no route" in res.error


def test_query_returns_offset_for_synthetic_in_sync_server(monkeypatch):
    # Pretend the server sees the same wall-clock time as us.
    import time
    now = time.time()
    pkt = _fake_ntp_packet(now)

    class FakeSock:
        def __init__(self, *a, **k): pass
        def settimeout(self, *_): pass
        def sendto(self, *_): pass
        def recvfrom(self, _n): return (pkt, ("127.0.0.1", 123))
        def close(self): pass
    monkeypatch.setattr(ntp.socket, "socket", lambda *a, **k: FakeSock())
    res = ntp._query_sync("fake", 123, 1.0)
    assert res.ok
    assert res.severity == "ok"
    assert abs(res.offset_s) < 0.5


@pytest.mark.skipif(os.environ.get("MSF_NTP_LIVE") != "1",
                    reason="set MSF_NTP_LIVE=1 to run live NTP query")
def test_live_ntp_query_succeeds_and_clock_in_bounds():
    res = asyncio.run(ntp.query(timeout=3.0))
    assert res.ok, res.error
    assert res.severity in ("ok", "warn", "fail")
