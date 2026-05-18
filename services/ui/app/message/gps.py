"""One-shot async GPS fetch.

The send / send_flow handlers call `fetch_current()` once per request to
get the latest fix from `services/gps` and hand the dict to
`templates.render()`. No background polling — every send is its own
moment in time.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8090"
TIMEOUT_S   = 1.5


def _url() -> str:
    return os.environ.get("GPS_URL", DEFAULT_URL).rstrip("/")


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_current() -> dict | None:
    """Latest fix from services/gps, or None if the service is unreachable.

    Returns the raw service payload (`{ok, latitude, longitude, altitude, ...}`)
    so callers can pass it straight to `templates.render(gps_fix=...)`.
    """
    try:
        return await asyncio.to_thread(_get_json, f"{_url()}/gps/current", TIMEOUT_S)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
