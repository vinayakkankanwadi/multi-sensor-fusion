"""ui — health, validators, templates, and end-to-end send flows.

Single file per service. UI is the SAPIENT sender; tests that drive the
full UI -> Apex -> registration_ack loop live here (Apex is the target,
not the system under test).
"""

from __future__ import annotations

import json
import uuid


NODE = "11111111-1111-1111-1111-111111111111"
ULID = "01HABCDEFGHJKMNPQRSTVWXYZ0"

EXPECTED_TEMPLATES = {
    "registration", "registration_ack", "status_report", "detection_report",
    "task", "task_ack", "alert", "alert_ack", "error",
}


def _validate(http, ui_url, raw: dict, node_id: str = NODE) -> dict:
    r = http.post(f"{ui_url}/api/validate", json={
        "node_id": node_id, "raw_json": json.dumps(raw),
    })
    assert r.status_code == 200, r.text
    return r.json()


def _has(errors: list[str], needle: str) -> bool:
    return any(needle.lower() in e.lower() for e in errors)


def _template_raw(http, ui_url, name: str) -> str:
    return http.get(f"{ui_url}/api/templates/{name}").json()["raw"]


# ---------- health -------------------------------------------------------

def test_health(http, ui_url):
    r = http.get(f"{ui_url}/api/health")
    assert r.status_code == 200


# ---------- validators (POST /api/validate) ------------------------------

def test_validator_rejects_no_content(http, ui_url):
    out = _validate(http, ui_url, {"timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}"})
    assert not out["ok"]
    assert _has(out["errors"], "content")


def test_validator_rejects_invalid_uuid(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "not-a-uuid",
        "registration": {"icdVersion": "BSI Flex 335 v2.0"},
    }, node_id="not-a-uuid")
    assert _has(out["errors"], "uuid")


def test_validator_rejects_missing_node_id(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "",
        "registration": {"icdVersion": "BSI Flex 335 v2.0"},
    }, node_id="")
    assert _has(out["errors"], "node_id") or _has(out["errors"], "nodeid")


def test_validator_registration_rejects_wrong_icd_version(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "registration": {
            "icdVersion": "BSI_Flex_335_v2.0",  # underscores: wrong
            "nodeDefinition": [{"nodeType": "NODE_TYPE_RADAR"}],
            "capabilities": [{"category": "x", "type": "y"}],
            "statusDefinition": {"statusInterval": {
                "units": "TIME_UNITS_SECONDS", "value": 1.0}},
            "modeDefinition": [{
                "modeName": "x", "modeType": "MODE_TYPE_DEFAULT",
                "settleTime": {"units": "TIME_UNITS_NANOSECONDS", "value": 1.0},
                "task": {"concurrentTasks": 1},
            }],
            "configData": [{"manufacturer": "x", "model": "y"}],
        },
    })
    assert _has(out["errors"], "BSI Flex 335 v2.0")


def test_validator_status_report_rejects_empty_mode(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "statusReport": {
            "reportId": ULID, "system": "SYSTEM_OK", "info": "INFO_NEW",
        },
    })
    assert _has(out["errors"], "mode")


def test_validator_status_report_rejects_invalid_ulid(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "statusReport": {
            "reportId": "not-a-ulid",
            "system": "SYSTEM_OK", "info": "INFO_NEW", "mode": "x",
        },
    })
    assert _has(out["errors"], "ulid")


def test_validator_detection_report_rejects_no_location(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "detectionReport": {"reportId": ULID, "objectId": ULID},
    })
    assert _has(out["errors"], "location") or _has(out["errors"], "range_bearing")


def test_validator_alert_rejects_out_of_range_ranking(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "alert": {"alertId": ULID, "ranking": 1.5},
    })
    assert _has(out["errors"], "ranking")


def test_validator_error_rejects_empty_packet(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "error": {"errorMessage": ["x"]},
    })
    assert _has(out["errors"], "packet")


def test_validator_task_rejects_unspecified_control(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "task": {"taskId": ULID},
    })
    assert _has(out["errors"], "control")


def test_validator_task_ack_rejects_unspecified_status(http, ui_url):
    out = _validate(http, ui_url, {
        "timestamp": "{{NOW}}", "nodeId": "{{NODE_ID}}",
        "taskAck": {"taskId": ULID},
    })
    assert _has(out["errors"], "task_status") or _has(out["errors"], "taskstatus")


# ---------- templates ----------------------------------------------------

def test_templates_list_returns_all_nine(http, ui_url):
    r = http.get(f"{ui_url}/api/templates")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert EXPECTED_TEMPLATES.issubset(names), f"missing: {EXPECTED_TEMPLATES - names}"


def test_templates_fetch_each_returns_raw_json(http, ui_url):
    for name in EXPECTED_TEMPLATES:
        r = http.get(f"{ui_url}/api/templates/{name}")
        assert r.status_code == 200, name
        body = r.json()
        assert "raw" in body
        assert "{{NODE_ID}}" in body["raw"], name
        assert "{{NOW}}" in body["raw"], name


def test_templates_registration_carries_icd_quirk(http, ui_url):
    raw = http.get(f"{ui_url}/api/templates/registration").json()["raw"]
    assert "BSI Flex 335 v2.0" in raw
    assert "concurrentTasks" in raw or "concurrent_tasks" in raw


def test_templates_status_report_has_nonempty_mode(http, ui_url):
    raw = http.get(f"{ui_url}/api/templates/status_report").json()["raw"]
    assert '"mode"' in raw


def test_templates_regenerate_rebuilds_all(http, ui_url):
    r = http.post(f"{ui_url}/api/templates/regenerate")
    assert r.status_code == 200
    after = {t["name"] for t in http.get(f"{ui_url}/api/templates").json()}
    assert EXPECTED_TEMPLATES.issubset(after)


def test_templates_every_template_passes_validator(http, ui_url):
    """Round-trip: every shipped template must satisfy its own validator."""
    for name in EXPECTED_TEMPLATES:
        raw = http.get(f"{ui_url}/api/templates/{name}").json()["raw"]
        out = http.post(f"{ui_url}/api/validate",
                        json={"node_id": NODE, "raw_json": raw}).json()
        assert out["ok"], f"{name}: {out['errors']}"


# ---------- send flows (UI -> Apex) --------------------------------------

def test_send_single_registration_to_apex_yields_ack(http, ui_url, apex_tcp):
    apex_host, apex_port = apex_tcp
    node_id = str(uuid.uuid4())
    r = http.post(f"{ui_url}/api/send", json={
        "host": apex_host, "port": apex_port, "node_id": node_id,
        "template_name": "registration",
        "raw_json": _template_raw(http, ui_url, "registration"),
        "recv_timeout_s": 5, "drain_after_s": 0.5,
        "validate_before_send": False,
    })
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["error"] is None
    assert any(t.get("direction") == "sent" and t.get("content") == "registration"
               for t in run["transcript"])
    assert any(t.get("direction") == "recv" and t.get("content") == "registration_ack"
               for t in run["transcript"])


def test_send_flow_registration_status_detection(http, ui_url, apex_tcp):
    apex_host, apex_port = apex_tcp
    node_id = str(uuid.uuid4())
    steps = [
        {"template_name": "registration",
         "raw_json": _template_raw(http, ui_url, "registration"),
         "wait_for": "registration_ack",
         "recv_timeout_s": 5, "drain_after_s": 0.5},
        {"template_name": "status_report",
         "raw_json": _template_raw(http, ui_url, "status_report"),
         "wait_for": None, "recv_timeout_s": 1, "drain_after_s": 0.5},
        {"template_name": "detection_report",
         "raw_json": _template_raw(http, ui_url, "detection_report"),
         "wait_for": None, "recv_timeout_s": 2, "drain_after_s": 0.5},
    ]
    r = http.post(f"{ui_url}/api/send_flow", json={
        "host": apex_host, "port": apex_port, "node_id": node_id,
        "validate_before_send": False, "steps": steps,
    }, timeout=15.0)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["error"] is None
    assert len(run["steps"]) == 3
    by_name = {s["template"]: s for s in run["steps"]}
    assert by_name["registration"]["sent"] is True
    assert by_name["registration"]["matched_wait_for"] == "registration_ack"
    assert by_name["status_report"]["sent"] is True
    assert by_name["detection_report"]["sent"] is True


def test_send_run_is_persisted_under_runs(http, ui_url, apex_tcp):
    apex_host, apex_port = apex_tcp
    node_id = str(uuid.uuid4())
    r = http.post(f"{ui_url}/api/send", json={
        "host": apex_host, "port": apex_port, "node_id": node_id,
        "template_name": "registration",
        "raw_json": _template_raw(http, ui_url, "registration"),
        "recv_timeout_s": 5, "drain_after_s": 0.5,
    })
    run_id = r.json()["run_id"]
    saved = http.get(f"{ui_url}/api/runs/{run_id}").json()
    assert saved["run_id"] == run_id
    assert saved["template"] == "registration"
    sent = saved.get("sent_message", {})
    assert sent.get("node_id") == node_id or sent.get("nodeId") == node_id
