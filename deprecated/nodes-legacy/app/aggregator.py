"""Per-node status aggregator.

A "node" is a platform host that provides one or more services (NTP, GPS,
…). The aggregator looks up each service's status from its owning service
(msf-ntp for `ntp`, msf-gps for `gps`) and rolls them up:

    node.severity = worst-of(service.severity for each enabled service)

Severity ranking: ok < warn < fail < unknown (unknown sorts last so a
service that hasn't been observed yet is treated as worse than fail).

This module is intentionally stateless. State (caches, polling) lives in
main.py; this file just builds the per-node view from already-fetched
upstream payloads.
"""

from __future__ import annotations

SEVERITY_RANK = {"ok": 0, "warn": 1, "fail": 2, "unknown": 3}


def _worst(severities: list[str]) -> str:
    if not severities:
        return "unknown"
    return max(severities, key=lambda s: SEVERITY_RANK.get(s, 99))


def _ntp_status_for_host(host: str, ntp_sources: dict) -> dict:
    """Look up a specific host inside msf-ntp's /ntp/sources payload.

    Returns a dict with at minimum {ok, severity}; additionally surfaces
    offset_s / rtt_s / error / last_ok_at when available. If the host
    isn't in msf-ntp's configured set, we return severity "unknown" with
    an explanatory error — the operator probably needs to add it to
    MSF_NTP_SERVERS for measurements to start arriving.
    """
    entry = (ntp_sources or {}).get("results", {}).get(host)
    if entry is None:
        return {"ok": False, "severity": "unknown",
                "error": f"host {host!r} not in msf-ntp's configured servers"}
    return {
        "ok": bool(entry.get("ok")),
        "severity": entry.get("severity") or "unknown",
        "offset_s": entry.get("offset_s"),
        "rtt_s": entry.get("rtt_s"),
        "error": entry.get("error"),
        "last_ok_at": entry.get("last_ok_at"),
    }


def _gps_status_for_host(host: str, gps_fix: dict) -> dict:
    """Decide if msf-gps's current fix is "coming from" this host.

    msf-gps doesn't track multiple upstreams today; it surfaces the
    last-seen sender IP in its `source` field, like
    `"udp/0.0.0.0:8500 (from 192.168.201.1)"`. If that IP matches the
    node's host and the fix is ok, we report green; if the fix is ok
    but from a different IP, we report unknown (this node hasn't been
    seen sending NMEA recently).
    """
    if not gps_fix:
        return {"ok": False, "severity": "unknown",
                "error": "msf-gps unreachable"}
    source = (gps_fix.get("source") or "")
    seen_from = None
    if "from " in source:
        seen_from = source.split("from ", 1)[1].rstrip(") ")
    if seen_from is None:
        return {"ok": False, "severity": "unknown",
                "error": "no NMEA received yet"}
    if seen_from != host:
        return {"ok": False, "severity": "unknown",
                "error": f"latest NMEA is from {seen_from}, not {host}"}
    if not gps_fix.get("ok"):
        return {"ok": False, "severity": "fail",
                "error": gps_fix.get("error") or "fix invalid"}
    return {
        "ok": True,
        "severity": "ok",
        "fix_status": gps_fix.get("fix_status"),
        "satellites": gps_fix.get("satellites"),
        "age_s": gps_fix.get("age_s"),
    }


def aggregate(node_cfg: dict,
              ntp_sources: dict | None,
              gps_fix: dict | None) -> dict:
    """Build a per-node status dict from a config entry + upstream snapshots."""
    services: dict[str, dict] = {}
    for kind in node_cfg.get("services", []):
        if kind == "ntp":
            services["ntp"] = _ntp_status_for_host(node_cfg["host"],
                                                    ntp_sources or {})
        elif kind == "gps":
            services["gps"] = _gps_status_for_host(node_cfg["host"],
                                                    gps_fix or {})
        else:
            services[kind] = {"ok": False, "severity": "unknown",
                              "error": f"no probe for service {kind!r}"}

    severities = [s.get("severity") or "unknown" for s in services.values()]
    overall = _worst(severities)
    ok = overall == "ok"
    return {
        "id": node_cfg["id"],
        "name": node_cfg["name"],
        "host": node_cfg["host"],
        "description": node_cfg.get("description", ""),
        "services_enabled": list(node_cfg.get("services", [])),
        "services": services,
        "severity": overall,
        "ok": ok,
    }
