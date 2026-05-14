"""TCP-connect probe for a SAPIENT middleware endpoint.

Stateless: open a TCP socket to (host, port) within budget, classify the
result, return a dict. The service layer calls this in parallel for
every configured middleware on each probe round.

Status semantics:
    ok      TCP connect succeeded inside `warn_after_s`.
    warn    TCP connect succeeded but took longer than `warn_after_s`.
    fail    Refused / unreachable / timed out within `timeout_s`.
    unknown only used by the caller when no probe has run yet.

A green "ok" means the port is reachable; it does *not* guarantee the
other side actually speaks SAPIENT. If we want a richer probe later
(send Registration → expect RegistrationAck), it can be a `kind`-aware
extension built on top of this.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass


@dataclass
class ProbeResult:
    ok: bool
    severity: str           # "ok" | "warn" | "fail"
    rtt_s: float | None
    error: str | None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "severity": self.severity,
            "rtt_s": self.rtt_s,
            "error": self.error,
        }


def _tcp_probe(host: str, port: int, timeout_s: float,
               warn_after_s: float) -> ProbeResult:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    t0 = time.time()
    try:
        sock.connect((host, port))
        rtt = time.time() - t0
        severity = "warn" if rtt > warn_after_s else "ok"
        return ProbeResult(True, severity, rtt, None)
    except socket.timeout:
        return ProbeResult(False, "fail",
                           time.time() - t0, f"timeout after {timeout_s:.1f}s")
    except (ConnectionRefusedError, OSError) as exc:
        return ProbeResult(False, "fail",
                           time.time() - t0, f"{type(exc).__name__}: {exc}")
    finally:
        sock.close()


async def probe(host: str, port: int,
                timeout_s: float = 1.5,
                warn_after_s: float = 0.5) -> ProbeResult:
    return await asyncio.to_thread(_tcp_probe, host, port, timeout_s, warn_after_s)
