"""cot-bridge — health, public ports, and CoT emission observability.

Public surface:
  - HTTP /health, /stats   (FastAPI on :8092)
  - TCP :5005 (SAPIENT in, length-prefix protobuf)
  - UDP out to TAK_HOST:TAK_PORT

CoT emission is observed via /stats deltas after driving a SAPIENT flow
through Apex (which Parent-forwardAlls to cot-bridge).
"""

from __future__ import annotations

import time
import uuid


def _template_raw(http, ui_url, name: str) -> str:
    return http.get(f"{ui_url}/api/templates/{name}").json()["raw"]


# ---------- health + ports -----------------------------------------------

def test_health(http, cot_bridge_url):
    r = http.get(f"{cot_bridge_url}/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_sapient_tcp_open(tcp_open, cot_bridge_tcp):
    host, port = cot_bridge_tcp
    assert tcp_open(host, port), f"cot-bridge :{port} not accepting"


# ---------- /stats counter contract --------------------------------------

def test_stats_endpoint_returns_counter_dict(cot_stats_snapshot):
    s = cot_stats_snapshot()
    for key in ("frames_in", "cot_out", "skipped_no_mapping",
                "skipped_no_position", "send_errors"):
        assert key in s, f"missing counter: {key}"
        assert isinstance(s[key], int)


def test_send_errors_counter_does_not_drift(cot_stats_snapshot):
    """No outbound UDP errors during a quiet moment."""
    a = cot_stats_snapshot()
    time.sleep(0.5)
    b = cot_stats_snapshot()
    assert b["send_errors"] == a["send_errors"], (
        f"send_errors drifted with no traffic: {a['send_errors']} -> {b['send_errors']}"
    )


# ---------- CoT emission end-to-end --------------------------------------

def test_registration_and_detection_emit_cot(http, ui_url, apex_tcp,
                                              cot_stats_snapshot):
    """Drive Registration + DetectionReport through Apex; expect cot_out
    to advance by >=2 (one CoT per mappable content type)."""
    before = cot_stats_snapshot()
    apex_host, apex_port = apex_tcp
    node_id = str(uuid.uuid4())
    steps = [
        {"template_name": "registration",
         "raw_json": _template_raw(http, ui_url, "registration"),
         "wait_for": "registration_ack",
         "recv_timeout_s": 5, "drain_after_s": 0.5},
        {"template_name": "detection_report",
         "raw_json": _template_raw(http, ui_url, "detection_report"),
         "wait_for": None, "recv_timeout_s": 2, "drain_after_s": 0.5},
    ]
    r = http.post(f"{ui_url}/api/send_flow", json={
        "host": apex_host, "port": apex_port, "node_id": node_id,
        "validate_before_send": False, "steps": steps,
    }, timeout=15.0)
    assert r.status_code == 200, r.text

    # Apex -> cot-bridge forwarding is asynchronous; poll up to 10s.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        after = cot_stats_snapshot()
        if (after["cot_out"] - before["cot_out"]) >= 2:
            break
        time.sleep(0.1)

    delta_cot    = after["cot_out"]   - before["cot_out"]
    delta_frames = after["frames_in"] - before["frames_in"]
    assert delta_frames >= 2, f"expected >=2 frames_in, got {delta_frames}"
    assert delta_cot    >= 2, f"expected >=2 cot_out (reg + detection), got {delta_cot}"
