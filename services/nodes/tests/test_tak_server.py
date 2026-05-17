"""tak-server probe — offline tests."""

from __future__ import annotations

import asyncio
import socket

from app.probes import tak_server


def _run(entry):
    return asyncio.run(tak_server.probe(entry, {}))


def test_unknown_by_default_for_udp_only_entry():
    n = _run({
        "id": "tak", "type": "tak-server", "name": "TAK",
        "host": "192.168.201.222", "port": 6969, "protocol": "udp",
    })
    assert n["severity"] == "unknown"
    assert n["ok"] is False
    assert n["probe_kind"] is None
    assert "UDP" in n["status"]["error"]


def test_tcp_admin_probe_ok_on_loopback():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    admin_port = srv.getsockname()[1]
    try:
        n = _run({
            "id": "tak", "type": "tak-server", "name": "TAK",
            "host": "127.0.0.1", "port": 6969,
            "probe_kind": "tcp", "admin_port": admin_port,
        })
        assert n["ok"] is True
        assert n["severity"] == "ok"
        assert n["probe_kind"] == "tcp"
        assert n["admin_port"] == admin_port
    finally:
        srv.close()


def test_tcp_admin_probe_fail_on_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    admin_port = s.getsockname()[1]
    s.close()
    n = _run({
        "id": "tak", "type": "tak-server", "name": "TAK",
        "host": "127.0.0.1", "port": 6969,
        "probe_kind": "tcp", "admin_port": admin_port,
    })
    assert n["ok"] is False
    assert n["severity"] == "fail"


def test_probe_kind_without_admin_port_falls_through_to_unknown():
    """If probe_kind=tcp is set but admin_port is missing, the probe shouldn't
    crash — it should behave like the default unknown case. (The service-side
    validator should also reject the bad combo at CRUD time, but the probe
    itself stays defensive.)"""
    n = _run({
        "id": "tak", "type": "tak-server", "name": "TAK",
        "host": "127.0.0.1", "port": 6969,
        "probe_kind": "tcp",
        # admin_port deliberately absent
    })
    assert n["severity"] == "unknown"
