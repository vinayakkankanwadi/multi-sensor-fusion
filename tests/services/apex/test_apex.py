"""Apex middleware — health + public ports.

Apex is the SAPIENT middleware (vendored from dstl/Apex-SAPIENT-Middleware/);
we treat it as a black box and verify its declared listeners are open.
Flows that drive messages through Apex via the UI live in test_ui.py.
"""

from __future__ import annotations


def test_health(http, apex_rest_url):
    # Apex's FastAPI app responds 200 on /. No dedicated /health.
    r = http.get(f"{apex_rest_url}/")
    assert r.status_code == 200


def test_child_tcp_open(tcp_open, apex_tcp):
    """Child v2 listener — the port the UI sends Registrations to."""
    host, port = apex_tcp
    assert tcp_open(host, port), f"apex child :{port} not open"


def test_parent_tcp_open(tcp_open):
    """Parent forwardAll listener — peer middleware connects here."""
    assert tcp_open("127.0.0.1", 5004), "apex parent :5004 not open"
