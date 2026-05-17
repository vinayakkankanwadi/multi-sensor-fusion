"""Regression-suite conftest.

The autouse fixture here blocks the session until every service the
regression tests depend on is reachable. Library unit tests (under
tests/libs/) don't import this, so they run without a stack.
"""

from __future__ import annotations

import time

import httpx
import pytest


@pytest.fixture(scope="session", autouse=True)
def _wait_for_stack(http, ui_url, nodes_url, gps_url, ntp_url, cot_bridge_url):
    checks = [
        (f"{ui_url}/api/health",       "ui"),
        (f"{nodes_url}/health",        "nodes"),
        (f"{gps_url}/health",          "gps"),
        (f"{ntp_url}/health",          "ntp"),
        (f"{cot_bridge_url}/health",   "cot-bridge"),
    ]
    deadline = time.monotonic() + 60
    for url, name in checks:
        while True:
            try:
                if http.get(url, timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.exit(
                    f"stack not ready: {name} ({url}) didn't respond within 60s",
                    returncode=2,
                )
            time.sleep(0.5)
