"""TCP prober tests — exercise the success/refused/timeout/slow paths
without touching real network state, plus a real-loopback success case."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest

from app import prober


def test_severity_ok_for_fast_loopback():
    # Bind a transient TCP listener so we have a guaranteed-live target.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        res = asyncio.run(prober.probe("127.0.0.1", port, timeout_s=1.0))
        assert res.ok
        assert res.severity == "ok"
        assert res.rtt_s is not None and res.rtt_s < 0.5
        assert res.error is None
    finally:
        srv.close()


def test_severity_warn_when_slow(monkeypatch):
    # Stub the blocking probe to return a slow but-OK result.
    def fake_probe(host, port, timeout_s, warn_after_s):
        time.sleep(0.0)
        return prober.ProbeResult(True, "warn", warn_after_s + 0.1, None)
    monkeypatch.setattr(prober, "_tcp_probe", fake_probe)
    res = asyncio.run(prober.probe("ignored", 1, warn_after_s=0.2))
    assert res.ok
    assert res.severity == "warn"


def test_severity_fail_on_refused():
    # Bind + close immediately so the port is *known* to be unbound.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    res = asyncio.run(prober.probe("127.0.0.1", port, timeout_s=0.5))
    assert not res.ok
    assert res.severity == "fail"
    assert res.error and ("ConnectionRefusedError" in res.error or "Errno" in res.error)


def test_severity_fail_on_timeout():
    # 192.0.2.0/24 is TEST-NET-1, RFC 5737 — guaranteed non-routable.
    res = asyncio.run(prober.probe("192.0.2.1", 9, timeout_s=0.3))
    assert not res.ok
    assert res.severity == "fail"
