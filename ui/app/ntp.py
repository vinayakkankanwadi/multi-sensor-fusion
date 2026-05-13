"""NTP time-sync probe.

The SAPIENT spec (§4.1) requires NTP-synced clocks. The reference Windows
harness validator stamps each message's timestamp; if the host clock drifts
by more than a few seconds, the harness can reject messages or produce
misleading results. This module measures clock offset against an NTP server
so the UI can warn the operator before they spend time chasing a sync issue.

Implementation: minimal NTP v3 client (no third-party dep). Sends a single
UDP packet to the configured server, parses the response, and returns the
offset (seconds, signed: positive = local clock ahead of server).
"""

from __future__ import annotations

import asyncio
import socket
import struct
import time
from dataclasses import dataclass

# NTP epoch is 1900-01-01; Unix epoch is 1970-01-01.
_NTP_TO_UNIX = 2208988800

DEFAULT_SERVER = "pool.ntp.org"
DEFAULT_PORT = 123
DEFAULT_TIMEOUT_S = 2.0
WARN_THRESHOLD_S = 0.5  # offset above this prompts a UI warning
FAIL_THRESHOLD_S = 2.0  # offset above this is treated as a hard failure


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
    """Synchronous NTP v3 query — used internally by the async wrapper."""
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

    # Fields we need: t1 (server receive), t2 (server transmit).
    # Bytes 32-39: receive timestamp. Bytes 40-47: transmit timestamp.
    rx_int, rx_frac = struct.unpack("!II", data[32:40])
    tx_int, tx_frac = struct.unpack("!II", data[40:48])
    t1 = (rx_int - _NTP_TO_UNIX) + rx_frac / 2**32
    t2 = (tx_int - _NTP_TO_UNIX) + tx_frac / 2**32

    # Standard NTP offset / round-trip computation.
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


async def query(server: str = DEFAULT_SERVER,
                port: int = DEFAULT_PORT,
                timeout: float = DEFAULT_TIMEOUT_S) -> NtpResult:
    """Async wrapper — runs the blocking socket call in a worker thread."""
    return await asyncio.to_thread(_query_sync, server, port, timeout)
