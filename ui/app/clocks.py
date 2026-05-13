"""Composite clock probe.

Returns three times in one shot:
  - NTP server time   (via app.ntp; defaults to MSF_NTP_SERVER, e.g. the LAN router)
  - Local container clock (== host clock, since the container shares the kernel)
  - Windows harness clock (extracted from a SAPIENT RegistrationAck timestamp)

…plus the pairwise deltas, so the UI can show one panel and the operator can
see at a glance whether everyone agrees.

The Windows probe re-uses the templates_loader + framer pipeline: render the
registration template, length-prefix it, send, read the first inbound frame,
parse it as a SapientMessage, and pull out `.timestamp`. No new wire format.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

from . import framer, ntp, templates_loader

log = logging.getLogger(__name__)


def _utc_iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class ClockSample:
    """One observation of (probe_time_local, observed_remote_time)."""
    label: str
    ok: bool
    local_time_iso: str | None  # local clock at the moment we observed
    remote_time_iso: str | None  # remote clock value
    rtt_s: float | None  # network round-trip if applicable
    error: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def local_clock(label: str = "local (container/host)") -> ClockSample:
    now = time.time()
    return ClockSample(
        label=label, ok=True,
        local_time_iso=_utc_iso(now),
        remote_time_iso=_utc_iso(now),  # remote = local for "self"
        rtt_s=0.0, error=None,
    )


async def ntp_clock(server: str | None = None,
                    timeout: float = 2.0) -> ClockSample:
    srv = server or os.environ.get("MSF_NTP_SERVER", ntp.DEFAULT_SERVER)
    t0 = time.time()
    res = await ntp.query(server=srv, timeout=timeout)
    t1 = time.time()
    label = f"NTP server ({srv})"
    if not res.ok or res.offset_s is None:
        return ClockSample(label=label, ok=False,
                           local_time_iso=_utc_iso(t1),
                           remote_time_iso=None,
                           rtt_s=res.rtt_s, error=res.error)
    # Reconstruct the server time at the probe midpoint:
    # remote_time ≈ local_time + offset
    remote = t1 + res.offset_s
    return ClockSample(label=label, ok=True,
                       local_time_iso=_utc_iso(t1),
                       remote_time_iso=_utc_iso(remote),
                       rtt_s=res.rtt_s, error=None)


async def windows_clock_via_sapient(
    *,
    host: str,
    port: int,
    node_id: str,
    template_name: str = "registration",
    connect_timeout_s: float = 3.0,
    recv_timeout_s: float = 3.0,
) -> ClockSample:
    """Open TCP to the Windows harness, send a Registration, read the
    RegistrationAck, return its timestamp as the harness clock at that moment.
    """
    label = f"Windows harness ({host}:{port})"
    if not host:
        return ClockSample(label=label, ok=False,
                           local_time_iso=None, remote_time_iso=None,
                           rtt_s=None, error="host is empty")

    try:
        text = templates_loader.get_template(template_name)
        message = templates_loader.render(text, node_id=node_id)
    except FileNotFoundError as exc:
        return ClockSample(label=label, ok=False,
                           local_time_iso=None, remote_time_iso=None,
                           rtt_s=None, error=f"template: {exc}")
    except Exception as exc:
        return ClockSample(label=label, ok=False,
                           local_time_iso=None, remote_time_iso=None,
                           rtt_s=None, error=f"render: {exc}")

    payload = message.SerializeToString()

    t0 = time.time()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=connect_timeout_s
        )
    except (socket.gaierror, OSError, asyncio.TimeoutError) as exc:
        return ClockSample(label=label, ok=False,
                           local_time_iso=_utc_iso(time.time()),
                           remote_time_iso=None,
                           rtt_s=None, error=f"connect: {exc}")
    try:
        writer.write(framer.encode(payload))
        await writer.drain()
        try:
            header = await asyncio.wait_for(
                reader.readexactly(framer.HEADER_LEN), timeout=recv_timeout_s)
            (length,) = framer._HEADER.unpack(header)
            body = await asyncio.wait_for(
                reader.readexactly(length), timeout=recv_timeout_s)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            return ClockSample(label=label, ok=False,
                               local_time_iso=_utc_iso(time.time()),
                               remote_time_iso=None,
                               rtt_s=None, error=f"read reply: {exc}")
        t1 = time.time()
        rtt = t1 - t0
        reply = _msg.SapientMessage()
        try:
            reply.ParseFromString(body)
        except Exception as exc:
            return ClockSample(label=label, ok=False,
                               local_time_iso=_utc_iso(t1),
                               remote_time_iso=None,
                               rtt_s=rtt, error=f"parse reply: {exc}")
        if not reply.HasField("timestamp"):
            return ClockSample(label=label, ok=False,
                               local_time_iso=_utc_iso(t1),
                               remote_time_iso=None,
                               rtt_s=rtt, error="reply has no timestamp")
        # Treat the Windows clock value as observed at the midpoint of the RTT.
        remote_secs = reply.timestamp.seconds + reply.timestamp.nanos / 1e9
        return ClockSample(label=label, ok=True,
                           local_time_iso=_utc_iso(t1 - rtt / 2),
                           remote_time_iso=_utc_iso(remote_secs),
                           rtt_s=rtt, error=None)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def _delta_seconds(iso_a: str | None, iso_b: str | None) -> float | None:
    """remote(a) − remote(b), in seconds; None if either is missing."""
    if not iso_a or not iso_b:
        return None
    a = datetime.strptime(iso_a, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    b = datetime.strptime(iso_b, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return (a - b).total_seconds()


def severity_for(offset_s: float | None) -> str:
    if offset_s is None:
        return "unknown"
    a = abs(offset_s)
    if a >= ntp.FAIL_THRESHOLD_S:
        return "fail"
    if a >= ntp.WARN_THRESHOLD_S:
        return "warn"
    return "ok"


def deltas_summary(local: ClockSample,
                   ntp_s: ClockSample,
                   windows: ClockSample | None) -> dict:
    """Build a summary of pairwise drifts. Reference = NTP server when available,
    otherwise local."""
    ref = ntp_s if ntp_s.ok else local
    out = {
        "reference_label": ref.label,
        "reference_time_iso": ref.remote_time_iso,
        "local_minus_ref_s": _delta_seconds(local.remote_time_iso, ref.remote_time_iso),
        "windows_minus_ref_s": _delta_seconds(
            windows.remote_time_iso if windows else None, ref.remote_time_iso),
        "windows_minus_local_s": _delta_seconds(
            windows.remote_time_iso if windows else None, local.remote_time_iso),
    }
    out["local_severity"] = severity_for(out["local_minus_ref_s"])
    out["windows_severity"] = severity_for(out["windows_minus_ref_s"])
    return out
