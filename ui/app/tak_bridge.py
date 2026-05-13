"""Optional TAK fan-out for the UI.

When the operator ticks "Also send to TAK" in the UI (or POSTs `/api/send`
with `also_send_to_tak=true`), the same SapientMessage we just put on the
wire to the middleware is also converted to a CoT XML event and sent over
UDP to the configured TAK Server CoT input.

The conversion lives in `sapient_to_cot/` (a separate package shared with
any future SAPIENT → CoT consumer such as the fusion node).

Position handling: messages without an explicit Location fall back to the
live router GPS fix (the same source as the {{GPS_LAT/LON/ALT}} template
placeholders), so a Registration with no location still drops a marker at
the edge node's location.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import time
from dataclasses import dataclass

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

import sapient_to_cot
from . import gps as _gps

log = logging.getLogger(__name__)

DEFAULT_HOST = os.environ.get("MSF_TAK_HOST", "192.168.201.102")
DEFAULT_PORT = int(os.environ.get("MSF_TAK_PORT", "6969"))


@dataclass
class TakSendResult:
    sent: bool
    bytes_sent: int = 0
    cot_type: str | None = None
    error: str | None = None
    skipped_reason: str | None = None
    target: str | None = None
    sent_uid: str | None = None
    echo: dict | None = None       # set when echo verification is awaited

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _gps_fallback() -> tuple[float | None, float | None, float | None]:
    """Return the most recent GPS fix we've ever seen, even if marked stale.

    A fresh container takes 5–10 s to receive its first NMEA datagram from
    the router. During that gap the snapshot has ok=False and we'd skip TAK
    fan-out — that's the "inconsistent" behaviour. Once we've parsed at
    least one valid fix we keep using its last lat/lon/alt as the fallback,
    so subsequent sends always have a position. The UI's clock-sync panel
    shows freshness/age separately so operators still know if the fix is old.
    """
    fix = _gps.current_fix()
    if fix.latitude is not None and fix.longitude is not None:
        return fix.latitude, fix.longitude, fix.altitude or 0.0
    return None, None, None


_UID_RE = re.compile(rb'uid="([^"]+)"')


def fan_out(message: _msg.SapientMessage,
            *, host: str | None = None, port: int | None = None) -> TakSendResult:
    """Convert + send. Never raises; returns a TakSendResult either way."""
    target_host = (host or DEFAULT_HOST or "").strip()
    target_port = port or DEFAULT_PORT
    if not target_host:
        return TakSendResult(sent=False, skipped_reason="no host configured")

    lat, lon, alt = _gps_fallback()
    try:
        payload = sapient_to_cot.convert(
            message, fallback_lat=lat, fallback_lon=lon, fallback_alt=alt)
    except Exception as exc:
        return TakSendResult(sent=False, error=f"convert: {exc}",
                             target=f"udp://{target_host}:{target_port}")

    if payload is None:
        content = message.WhichOneof("content")
        return TakSendResult(
            sent=False,
            skipped_reason=(
                f"no CoT mapping for content={content}"
                if content not in ("registration", "status_report",
                                   "detection_report", "alert")
                else "no position available (set a location in the message or "
                     "wait for GPS fix)"),
            target=f"udp://{target_host}:{target_port}",
        )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        sent = sock.sendto(payload, (target_host, target_port))
        sock.close()
    except Exception as exc:
        return TakSendResult(sent=False, error=f"send: {exc}",
                             target=f"udp://{target_host}:{target_port}")

    # Pull the CoT type and uid out for the transcript / echo correlation.
    cot_type = None
    uid = None
    try:
        i = payload.find(b'type="')
        if i >= 0:
            j = payload.find(b'"', i + 6)
            cot_type = payload[i + 6:j].decode("ascii", errors="replace")
    except Exception:
        pass
    m = _UID_RE.search(payload)
    if m:
        uid = m.group(1).decode("ascii", errors="replace")

    return TakSendResult(sent=True, bytes_sent=sent, cot_type=cot_type,
                         target=f"udp://{target_host}:{target_port}",
                         sent_uid=uid)


async def fan_out_with_echo(message: _msg.SapientMessage, *,
                             host: str | None = None,
                             port: int | None = None,
                             echo_timeout_s: float = 4.0) -> TakSendResult:
    """fan_out + await echo. Echo result lives in `result.echo` (dict)."""
    from . import tak_echo
    publish_t = time.monotonic()
    res = fan_out(message, host=host, port=port)
    if not res.sent or not res.sent_uid:
        return res
    if tak_echo.listener is None:
        res.echo = {"matched": False, "reason": "echo listener not running"}
        return res
    res.echo = await tak_echo.listener.await_echo(
        res.sent_uid, timeout=echo_timeout_s, publish_time=publish_t)
    return res
