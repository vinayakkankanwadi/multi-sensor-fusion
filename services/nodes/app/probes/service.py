"""service probe — health-check the containers we spin (ui, gps,
ntp, nodes, apex, cot-bridge, …).

A `service` entry in nodes.json describes one of our own containers. Two
probe modes, picked by entry fields:

    health_path: "/health"     HTTP GET host:port + path; expect 2xx
    probe_kind:  "tcp"         bare TCP connect (for non-HTTP services
                               like cot-bridge that only listen on a
                               protocol port)

If neither is set the probe returns "unknown" — fail-fast so we don't
silently report a service as healthy because we forgot to configure how
to check it.
"""

from __future__ import annotations

import asyncio
import socket
import time
import urllib.error
import urllib.request

TIMEOUT_S = 2.0
WARN_AFTER_S = 0.5


def _classify_rtt(rtt: float) -> str:
    return "warn" if rtt > WARN_AFTER_S else "ok"


def _http_probe(host: str, port: int, path: str) -> dict:
    url = f"http://{host}:{port}{path}"
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            rtt = time.time() - t0
            if 200 <= resp.status < 300:
                return {"ok": True, "severity": _classify_rtt(rtt),
                        "rtt_s": rtt, "error": None}
            return {"ok": False, "severity": "fail", "rtt_s": rtt,
                    "error": f"HTTP {resp.status}"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"{type(exc).__name__}: {exc}"}


def _tcp_probe(host: str, port: int) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_S)
    t0 = time.time()
    try:
        sock.connect((host, port))
        rtt = time.time() - t0
        return {"ok": True, "severity": _classify_rtt(rtt),
                "rtt_s": rtt, "error": None}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        sock.close()


async def probe(entry: dict, ctx: dict) -> dict:
    if entry.get("health_path"):
        res = await asyncio.to_thread(
            _http_probe, entry["host"], int(entry["port"]),
            entry["health_path"],
        )
        probe_kind = "http"
    elif entry.get("probe_kind") == "tcp":
        res = await asyncio.to_thread(
            _tcp_probe, entry["host"], int(entry["port"]),
        )
        probe_kind = "tcp"
    else:
        return {
            "probe_kind": None,
            "status": {"ok": False, "severity": "unknown", "rtt_s": None,
                       "error": "no probe configured (need health_path or probe_kind=tcp)"},
            "severity": "unknown",
            "ok": False,
        }
    return {
        "probe_kind": probe_kind,
        "status": res,
        "severity": res["severity"],
        "ok": res["ok"],
    }
