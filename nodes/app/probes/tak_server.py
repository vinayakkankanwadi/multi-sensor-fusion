"""tak-server probe — TAK Server registry entry.

TAK's primary surface is **UDP CoT ingest** (typically `:6969`). UDP has
no handshake and packets are dropped silently on the receiver side, so a
TAK Server cannot be meaningfully probed at the protocol level: sending a
test datagram doesn't tell us whether anything received it. Returning a
fake "ok" because the entry is configured would lie; this probe returns
**`unknown`** by default with an honest reason in the error field.

Operators who genuinely want a liveness signal can configure an optional
TCP admin port (TAK Server has one — e.g. 8089 for marti) and add:

    "probe_kind": "tcp",
    "admin_port": 8089

The probe then TCP-connects to `host:admin_port`. Same severity ladder as
the service / middleware probes (ok < warn-if-slow < fail). The CoT port
itself is left alone — `port` in the entry is the *send target* address
operators want surfaced in the UI, not something to probe.
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
        sev = "warn" if rtt > WARN_AFTER_S else "ok"
        return {"ok": True, "severity": sev, "rtt_s": rtt, "error": None}
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        return {"ok": False, "severity": "fail", "rtt_s": time.time() - t0,
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        sock.close()


async def probe(entry: dict, ctx: dict) -> dict:
    if entry.get("probe_kind") == "tcp" and entry.get("admin_port"):
        res = await asyncio.to_thread(
            _tcp_probe, entry["host"], int(entry["admin_port"]),
        )
        return {
            "probe_kind": "tcp",
            "admin_port": int(entry["admin_port"]),
            "status": res,
            "severity": res["severity"],
            "ok": res["ok"],
        }
    return {
        "probe_kind": None,
        "status": {
            "ok": False,
            "severity": "unknown",
            "rtt_s": None,
            "error": "UDP CoT ingest cannot be probed at the protocol level; "
                     "add 'probe_kind': 'tcp' + 'admin_port' to TCP-check the "
                     "TAK admin port instead",
        },
        "severity": "unknown",
        "ok": False,
    }
