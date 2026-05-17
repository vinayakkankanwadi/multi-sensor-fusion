"""NTP v3 probe — single-server query, used by the multi-source poller.

Stateless protocol code: build a v3 client packet, send to `server:port`,
parse the reply, return offset / RTT / severity. No third-party deps.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass

# NTP epoch is 1900-01-01; Unix epoch is 1970-01-01.
_NTP_TO_UNIX = 2208988800

DEFAULT_PORT = 123
DEFAULT_TIMEOUT_S = 2.0
WARN_THRESHOLD_S = 0.5
FAIL_THRESHOLD_S = 2.0


@dataclass
class NtpResult:
    server: str
    ok: bool
    offset_s: float | None
    rtt_s: float | None
    error: str | None
    severity: str  # "ok" | "warn" | "fail"

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "ok": self.ok,
            "offset_s": self.offset_s,
            "rtt_s": self.rtt_s,
            "error": self.error,
            "severity": self.severity,
            "warn_threshold_s": WARN_THRESHOLD_S,
            "fail_threshold_s": FAIL_THRESHOLD_S,
        }


def _query_sync(server: str, port: int, timeout: float) -> NtpResult:
    # NTP v3 client request: LI=0, VN=3, Mode=3 → 0x1B.
    request = b"\x1b" + b"\0" * 47

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        addr = (server, port)
        t0 = time.time()
        sock.sendto(request, addr)
        data, _ = sock.recvfrom(48)
        t3 = time.time()
    except (socket.timeout, OSError) as exc:
        return NtpResult(server, False, None, None, f"network: {exc}", "fail")
    finally:
        sock.close()

    if len(data) < 48:
        return NtpResult(server, False, None, None,
                         f"short reply: {len(data)} bytes", "fail")

    rx_int, rx_frac = struct.unpack("!II", data[32:40])
    tx_int, tx_frac = struct.unpack("!II", data[40:48])
    t1 = (rx_int - _NTP_TO_UNIX) + rx_frac / 2**32
    t2 = (tx_int - _NTP_TO_UNIX) + tx_frac / 2**32

    offset = ((t1 - t0) + (t2 - t3)) / 2.0
    rtt = (t3 - t0) - (t2 - t1)

    abs_offset = abs(offset)
    if abs_offset >= FAIL_THRESHOLD_S:
        severity = "fail"
    elif abs_offset >= WARN_THRESHOLD_S:
        severity = "warn"
    else:
        severity = "ok"

    return NtpResult(server, True, offset, rtt, None, severity)


async def query(server: str,
                port: int = DEFAULT_PORT,
                timeout: float = DEFAULT_TIMEOUT_S) -> NtpResult:
    return await asyncio.to_thread(_query_sync, server, port, timeout)
