"""NTP accessor — thin HTTP client to the ntp service.

The actual UDP probe lives in ntp, which polls one-or-more NTP
servers and exposes a voted answer over HTTP. The UI just asks
`GET /ntp/current` and shapes the result into the same `NtpResult`
the rest of the UI already speaks.

Configure via:
    NTP_URL  base URL of the ntp service (default http://127.0.0.1:8091)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_NTP_URL = "http://127.0.0.1:8091"
HTTP_TIMEOUT_S = 1.5

# Severity thresholds — surfaced by the service but mirrored here so any
# in-UI math (e.g. badge colour) doesn't need an HTTP round-trip.
WARN_THRESHOLD_S = 0.5
FAIL_THRESHOLD_S = 2.0
DEFAULT_SERVER = "ntp"  # cosmetic — label, not a hostname
DEFAULT_TIMEOUT_S = 2.0     # kept for /api/ntp?timeout= compat


@dataclass
class NtpResult:
    server: str
    ok: bool
    offset_s: float | None
    rtt_s: float | None
    error: str | None
    severity: str

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


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _service_url() -> str:
    return os.environ.get("NTP_URL", DEFAULT_NTP_URL).rstrip("/")


def _result_from_dict(d: dict, label: str) -> NtpResult:
    return NtpResult(
        server=label,
        ok=bool(d.get("ok")),
        offset_s=d.get("offset_s"),
        rtt_s=d.get("rtt_s"),
        error=d.get("error"),
        severity=str(d.get("severity") or "fail"),
    )


async def query(server: str | None = None,
                port: int | None = None,
                timeout: float = DEFAULT_TIMEOUT_S) -> NtpResult:
    """Fetch the voted offset from ntp. `server` is accepted only for
    backwards compatibility with callers that used to name an NTP host;
    the UI now delegates source selection to the ntp service."""
    base = _service_url()
    label = server or f"ntp ({base})"
    url = f"{base}/ntp/current"
    try:
        data = await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
        return _result_from_dict(data, label=label)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return NtpResult(label, False, None, None,
                         f"ntp service unreachable: {exc}", "fail")
    except Exception as exc:
        return NtpResult(label, False, None, None,
                         f"ntp service error: {exc}", "fail")
