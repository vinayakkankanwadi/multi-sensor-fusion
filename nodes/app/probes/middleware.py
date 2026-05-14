"""middleware probe — TCP-connect probe for a SAPIENT-speaking endpoint
(Apex, BSI Windows harness, future Python middleware, …).

Stateless: open a TCP socket to (host, port) within budget, classify the
result, return a status dict. Honours an optional per-entry `probe: false`
flag — useful for endpoints whose logs are sensitive to bare connect/close
churn (e.g. the BSI Windows harness, which records each one as a receiver
error).

Status semantics:
    ok      TCP connect succeeded within warn_after_s
    warn    TCP connect succeeded but slower than warn_after_s
    fail    Refused / unreachable / timed out within timeout_s
    unknown probing intentionally disabled via "probe": false
"""

from __future__ import annotations

import asyncio
import socket
import time

TIMEOUT_S = 1.5
WARN_AFTER_S = 0.5


def _tcp_probe(host: str, port: int) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_S)
    t0 = time.time()
    try:
        sock.connect((host, port))
        rtt = time.time() - t0
        severity = "warn" if rtt > WARN_AFTER_S else "ok"
        return {"ok": True, "severity": severity, "rtt_s": rtt, "error": None}
    except socket.timeout:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"timeout after {TIMEOUT_S:.1f}s"}
    except (ConnectionRefusedError, OSError) as exc:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        sock.close()


async def probe(entry: dict, ctx: dict) -> dict:
    if not entry.get("probe", True):
        return {
            "kind": entry.get("kind"),
            "status": {"ok": False, "severity": "unknown", "rtt_s": None,
                       "error": "probing disabled in config"},
            "severity": "unknown",
            "ok": False,
        }
    res = await asyncio.to_thread(_tcp_probe, entry["host"], int(entry["port"]))
    return {
        "kind": entry.get("kind"),
        "status": res,
        "severity": res["severity"],
        "ok": res["ok"],
    }
