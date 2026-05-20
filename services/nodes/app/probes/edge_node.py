"""edge-node probe — composes per-service health (NTP, GPS) from the
external service-of-record (ntp + gps) into one rolled-up status.

An edge node is an upstream host that *provides* services to the rest
of the stack (today: the router, which serves both NTP and GPS NMEA).
The node's overall severity is the worst of its enabled services.
"""

from __future__ import annotations

SEV_RANK = {"ok": 0, "warn": 1, "fail": 2, "unknown": 3}


def _worst(severities: list[str]) -> str:
    if not severities:
        return "unknown"
    return max(severities, key=lambda s: SEV_RANK.get(s, 99))


def _ntp_status_for_host(host: str, ntp_sources: dict) -> dict:
    entry = (ntp_sources or {}).get("results", {}).get(host)
    if entry is None:
        return {"ok": False, "severity": "unknown",
                "error": f"host {host!r} not in ntp's configured servers"}
    return {
        "ok": bool(entry.get("ok")),
        "severity": entry.get("severity") or "unknown",
        "offset_s": entry.get("offset_s"),
        "rtt_s": entry.get("rtt_s"),
        "error": entry.get("error"),
        "last_ok_at": entry.get("last_ok_at"),
    }


# Router pushes NMEA at ~1 Hz. If the latest sentence is older than
# this, treat the link as down (red dot) — matches the panel's view.
GPS_FRESH_S = 8.0


def _gps_status_for_host(host: str, gps_fix: dict) -> dict:
    if not gps_fix:
        return {"ok": False, "severity": "fail", "error": "gps unreachable"}
    source = (gps_fix.get("source") or "")
    seen_from = None
    if "from " in source:
        seen_from = source.split("from ", 1)[1].rstrip(") ")
    if seen_from is None:
        return {"ok": False, "severity": "fail", "error": "no NMEA received yet"}
    if seen_from != host:
        return {"ok": False, "severity": "fail",
                "error": f"latest NMEA is from {seen_from}, not {host}"}
    age = gps_fix.get("age_s")
    if not isinstance(age, (int, float)) or age > GPS_FRESH_S:
        return {"ok": False, "severity": "fail",
                "error": f"NMEA stale ({age}s ago, threshold {GPS_FRESH_S}s)",
                "age_s": age}
    if not gps_fix.get("ok"):
        return {"ok": False, "severity": "fail",
                "error": gps_fix.get("error") or "fix invalid",
                "age_s": age}
    return {
        "ok": True,
        "severity": "ok",
        "fix_status": gps_fix.get("fix_status"),
        "satellites": gps_fix.get("satellites"),
        "age_s": age,
    }


async def probe(entry: dict, ctx: dict) -> dict:
    """Aggregate per-service health for this entry. `ctx` carries the
    pre-fetched ntp `/ntp/sources` payload and gps `/gps/current`
    payload — fetching them is the orchestrator's job, this stays pure."""
    services: dict[str, dict] = {}
    for kind in entry.get("services", []):
        if kind == "ntp":
            services["ntp"] = _ntp_status_for_host(entry["host"],
                                                    ctx.get("ntp_sources") or {})
        elif kind == "gps":
            services["gps"] = _gps_status_for_host(entry["host"],
                                                    ctx.get("gps_fix") or {})
        else:
            services[kind] = {"ok": False, "severity": "unknown",
                              "error": f"no probe for service {kind!r}"}

    severities = [s.get("severity") or "unknown" for s in services.values()]
    overall = _worst(severities)
    return {
        "services_enabled": list(entry.get("services", [])),
        "services": services,
        "severity": overall,
        "ok": overall == "ok",
    }
