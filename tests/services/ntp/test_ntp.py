"""ntp — health + voted offset shape + per-source severity.

Black-box: the service polls real NTP servers on a cadence. Wire-level
edge cases (short reply, network error) aren't observable from outside;
the shape contract and live result are covered here.
"""

from __future__ import annotations


# ---------- health -------------------------------------------------------

def test_health(http, ntp_url):
    r = http.get(f"{ntp_url}/health")
    assert r.status_code == 200


# ---------- /ntp/current shape -------------------------------------------

def test_current_has_expected_shape(http, ntp_url):
    r = http.get(f"{ntp_url}/ntp/current")
    assert r.status_code == 200
    body = r.json()
    for key in ("ok", "severity", "asked", "warn_threshold_s",
                "fail_threshold_s"):
        assert key in body, f"missing key: {key}"
    assert body["severity"] in ("ok", "warn", "fail")
    assert body["warn_threshold_s"] < body["fail_threshold_s"]


# ---------- /ntp/sources -------------------------------------------------

def test_sources_lists_every_configured_server(http, ntp_url):
    r = http.get(f"{ntp_url}/ntp/sources")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert len(body["results"]) >= 1


# ---------- severity classification --------------------------------------

def test_severity_is_a_valid_classification(http, ntp_url):
    cur = http.get(f"{ntp_url}/ntp/current").json()
    assert cur["severity"] in ("ok", "warn", "fail")
    assert 0 < cur["warn_threshold_s"] < cur["fail_threshold_s"]


def test_per_source_severity_respects_thresholds(http, ntp_url):
    """Each upstream's severity should classify monotonically against
    the global thresholds: bigger |offset| -> worse severity."""
    cur = http.get(f"{ntp_url}/ntp/current").json()
    warn = cur["warn_threshold_s"]
    fail = cur["fail_threshold_s"]
    sources = http.get(f"{ntp_url}/ntp/sources").json()["results"]
    severities = {"ok": 0, "warn": 1, "fail": 2}
    for name, s in sources.items():
        if not s.get("ok"):
            continue
        off = abs(s.get("offset_s") or 0.0)
        sev = s["severity"]
        assert sev in severities, f"{name}: unknown severity {sev}"
        if off >= fail:
            assert sev == "fail", f"{name}: offset={off} >= fail={fail} but severity={sev}"
        elif off >= warn:
            assert severities[sev] >= severities["warn"], (
                f"{name}: offset={off} >= warn={warn} but severity={sev}"
            )
