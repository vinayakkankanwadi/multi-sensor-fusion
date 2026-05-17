"""middleware probe — offline tests (real loopback + synthetic failures)."""

from __future__ import annotations

import asyncio
import socket

from app.probes import middleware as mw


def _run(entry):
    return asyncio.run(mw.probe(entry, {}))


def _entry(host, port, probe=True):
    return {"id": "x", "type": "middleware", "name": "x",
            "host": host, "port": port, "probe": probe}


def test_ok_for_fast_loopback():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        n = _run(_entry("127.0.0.1", port))
        assert n["ok"]
        assert n["severity"] == "ok"
        assert n["status"]["rtt_s"] is not None and n["status"]["rtt_s"] < 0.5
    finally:
        srv.close()


def test_fail_on_refused():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # port now unbound -> refused
    n = _run(_entry("127.0.0.1", port))
    assert not n["ok"]
    assert n["severity"] == "fail"


def test_fail_on_timeout_to_unreachable():
    # RFC 5737 TEST-NET-1 — guaranteed non-routable.
    n = _run(_entry("192.0.2.1", 9))
    assert not n["ok"]
    assert n["severity"] == "fail"


def test_probe_false_is_unknown_not_fail():
    # Wrong port deliberately — if we *did* probe, this would be fail.
    n = _run(_entry("127.0.0.1", 1, probe=False))
    assert n["severity"] == "unknown"
    assert "probing disabled" in n["status"]["error"]
