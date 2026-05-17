"""Shared fixtures for the whole regression suite.

These fixtures encode the *only* assumption regression tests make about
the system: the public URLs and ports each service exposes. Internal
modules, file paths, and shapes are off-limits — if a test needs to know
something black-box can't see, that's a gap we file against the service.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Iterable

import httpx
import pytest


# All services run with network_mode: host, so 127.0.0.1 is the right
# address for every dial. Override via env if running the test container
# anywhere else.
def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@pytest.fixture(scope="session")
def ui_url() -> str:
    return _env("UI_URL", "http://127.0.0.1:8080")


@pytest.fixture(scope="session")
def nodes_url() -> str:
    return _env("NODES_URL", "http://127.0.0.1:8093")


@pytest.fixture(scope="session")
def gps_url() -> str:
    return _env("GPS_URL", "http://127.0.0.1:8090")


@pytest.fixture(scope="session")
def ntp_url() -> str:
    return _env("NTP_URL", "http://127.0.0.1:8091")


@pytest.fixture(scope="session")
def cot_bridge_url() -> str:
    return _env("COT_BRIDGE_URL", "http://127.0.0.1:8092")


@pytest.fixture(scope="session")
def apex_rest_url() -> str:
    return _env("APEX_REST_URL", "http://127.0.0.1:8081")


@pytest.fixture(scope="session")
def apex_tcp() -> tuple[str, int]:
    host = _env("APEX_HOST", "127.0.0.1")
    port = int(_env("APEX_PORT", "5020"))
    return host, port


@pytest.fixture(scope="session")
def cot_bridge_tcp() -> tuple[str, int]:
    return (_env("COT_BRIDGE_HOST", "127.0.0.1"),
            int(_env("COT_BRIDGE_PORT", "5005")))


@pytest.fixture(scope="session")
def gps_nmea_endpoint() -> tuple[str, int]:
    return (_env("GPS_NMEA_HOST", "127.0.0.1"),
            int(_env("GPS_NMEA_PORT", "8500")))


@pytest.fixture(scope="session")
def http() -> Iterable[httpx.Client]:
    """Session HTTP client. 5s default timeout — enough for the slowest
    public endpoint (template regen does protoc work)."""
    with httpx.Client(timeout=10.0) as c:
        yield c


@pytest.fixture
def tcp_open():
    """Return a fn(host, port, timeout=2) -> bool that opens+closes a TCP."""
    def _check(host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
    return _check


@pytest.fixture
def udp_send():
    """Return a fn(host, port, payload: bytes) that fires UDP and returns."""
    def _send(host: str, port: int, payload: bytes) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto(payload, (host, port))
        finally:
            s.close()
    return _send


@pytest.fixture
def cot_stats_snapshot(http, cot_bridge_url):
    """Snapshot cot-bridge /stats — handy for asserting a flow incremented
    cot_out / skipped counters."""
    def _snap() -> dict:
        r = http.get(f"{cot_bridge_url}/stats", timeout=2.0)
        r.raise_for_status()
        return r.json()
    return _snap


@pytest.fixture
def created_node(http, nodes_url):
    """Context fixture: POST a node, yield its id, DELETE on teardown.

        def test_xyz(created_node):
            nid = created_node({"id": "test-mw", "type": "middleware",
                                "name": "T", "host": "127.0.0.1", "port": 5020,
                                "kind": "apex"})
            ...
    """
    created_ids: list[str] = []

    def _create(payload: dict) -> str:
        r = http.post(f"{nodes_url}/nodes", json=payload)
        assert r.status_code == 201, f"POST /nodes failed: {r.status_code} {r.text}"
        nid = r.json()["id"]
        created_ids.append(nid)
        return nid

    yield _create

    for nid in created_ids:
        try:
            http.delete(f"{nodes_url}/nodes/{nid}", timeout=2.0)
        except httpx.HTTPError:
            pass


# ---------- final summary banner ----------------------------------------
# At the end of every run, print one line per test file with a coloured
# status: green OK, yellow WARN (skipped/xfailed), red FAIL. Gives an
# at-a-glance verdict per component without scrolling the full output.

import json
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone


# Output JSON consumed by tests/server.py /result endpoint.
RESULT_JSON = Path("/tmp/last_run.json")


def _bucket_per_file(stats: dict) -> dict:
    """Group pytest report objects by test file, counting per outcome."""
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "skipped": 0}
    )
    for outcome in ("passed", "failed", "skipped"):
        for report in stats.get(outcome, []):
            nodeid = getattr(report, "nodeid", "") or ""
            f = nodeid.split("::", 1)[0]
            if not f or "warnings summary" in f.lower():
                continue
            if f.startswith("/work/tests/"):
                f = f[len("/work/tests/"):]
            elif f.startswith("tests/"):
                f = f[len("tests/"):]
            counts[f][outcome] += 1
    return counts


def _file_status(c: dict) -> str:
    if c["failed"] > 0:
        return "fail"
    if c["skipped"] > 0:
        return "warn"
    return "ok"


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    counts = _bucket_per_file(tr.stats)
    if not counts:
        return

    # 1) Colored banner — for humans running pytest from the CLI.
    tr.write_sep("=", "summary by test file", bold=True)
    for f in sorted(counts):
        c = counts[f]
        st = _file_status(c)
        status, kw = {
            "ok":   ("  OK  ", {"green":  True, "bold": True}),
            "warn": (" WARN ", {"yellow": True, "bold": True}),
            "fail": (" FAIL ", {"red":    True, "bold": True}),
        }[st]
        line = (f"  [{status}]  {f:60s}  "
                f"passed={c['passed']:3d}  failed={c['failed']:2d}  skipped={c['skipped']:2d}")
        tr.write_line(line, **kw)

    # 2) Structured JSON — for tests/server.py /result endpoint.
    totals = {"passed": 0, "failed": 0, "skipped": 0}
    per_file = []
    for f in sorted(counts):
        c = counts[f]
        per_file.append({"file": f, "status": _file_status(c), **c})
        for k in totals:
            totals[k] += c[k]
    payload = {
        "exit_code": int(exitstatus),
        "overall_status": "fail" if totals["failed"] else ("warn" if totals["skipped"] else "ok"),
        "totals": totals,
        "per_file": per_file,
        "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        RESULT_JSON.write_text(json.dumps(payload, indent=2))
    except OSError:
        pass  # /tmp not writable in some envs — banner still printed
