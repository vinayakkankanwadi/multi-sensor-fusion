"""Internal GPS fix cache for template substitution.

The NMEA UDP listener lives in `services/gps`. The UI doesn't expose a
GPS endpoint itself — but `{{GPS_LAT}}` / `{{GPS_LON}}` / `{{GPS_ALT}}`
placeholders in templates are substituted in the *synchronous* path of
`templates_loader.render()`. So this module runs a 1 s background poll
against the gps service and exposes a non-blocking accessor.

Configure via:
    GPS_URL  base URL of the gps service (default http://127.0.0.1:8090)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

DEFAULT_GPS_URL = "http://127.0.0.1:8090"
POLL_INTERVAL_S = 1.0
HTTP_TIMEOUT_S = 1.5


@dataclass
class GpsFix:
    ok: bool
    error: str | None
    source: str
    fix_status: str | None
    latitude: float | None
    longitude: float | None
    altitude: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _empty_fix(error: str) -> GpsFix:
    return GpsFix(ok=False, error=error, source="gps",
                  fix_status=None, latitude=None, longitude=None, altitude=None)


_LATEST: GpsFix = _empty_fix("gps poller not started")
_POLL_TASK: asyncio.Task | None = None


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _poll_loop(url: str) -> None:
    global _LATEST
    log.info("gps poller targeting %s", url)
    while True:
        try:
            d = await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
            _LATEST = GpsFix(
                ok=bool(d.get("ok")),
                error=d.get("error"),
                source=str(d.get("source") or "gps"),
                fix_status=d.get("fix_status"),
                latitude=d.get("latitude"),
                longitude=d.get("longitude"),
                altitude=d.get("altitude"),
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _LATEST = _empty_fix(f"gps service unreachable: {exc}")
        except Exception as exc:
            log.warning("gps poll: unexpected error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_S)


async def start_poller() -> None:
    global _POLL_TASK
    base = os.environ.get("GPS_URL", DEFAULT_GPS_URL).rstrip("/")
    _POLL_TASK = asyncio.create_task(_poll_loop(f"{base}/gps/current"))


async def stop_poller() -> None:
    global _POLL_TASK
    if _POLL_TASK:
        _POLL_TASK.cancel()
        try:
            await _POLL_TASK
        except (asyncio.CancelledError, Exception):
            pass
        _POLL_TASK = None


def current_fix() -> GpsFix:
    """Latest fix from the background poller. Cheap, sync, safe to call
    from any context — does no I/O itself."""
    return _LATEST
