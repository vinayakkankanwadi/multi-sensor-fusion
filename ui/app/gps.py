"""GPS accessor — thin HTTP client to the gps service.

The NMEA UDP listener now lives in its own service (gps). The UI
keeps a one-second background poll going so synchronous callers (template
substitution for `{{GPS_LAT}}` etc.) get the latest fix without doing
HTTP themselves and without blocking the event loop.

Configure via:
    GPS_URL  base URL of the gps service (default http://127.0.0.1:8090)
"""

from __future__ import annotations

import asyncio
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
    accuracy: float | None
    satellites: int | None
    speed: float | None
    angle: float | None
    timestamp: str | None
    last_sentence: str | None
    age_s: float | None
    raw: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def _empty_fix(error: str, source: str = "(none)") -> GpsFix:
    return GpsFix(
        ok=False, error=error, source=source,
        fix_status=None, latitude=None, longitude=None, altitude=None,
        accuracy=None, satellites=None, speed=None, angle=None,
        timestamp=None, last_sentence=None, age_s=None, raw=None,
    )


# Module-level state, refreshed by the lifespan poller.
_LATEST: GpsFix = _empty_fix("gps poller not started")
_LATEST_RAW: dict = {"error": "gps poller not started"}
_POLL_TASK: asyncio.Task | None = None
_LAST_FETCH_OK_AT: float = 0.0
GPS_URL: str = DEFAULT_GPS_URL


def _http_get_json(url: str, timeout: float) -> dict:
    """Sync HTTP GET → JSON dict. Used inside the async poller via
    `asyncio.to_thread` so it doesn't block the event loop."""
    import json
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fix_from_dict(d: dict) -> GpsFix:
    return GpsFix(
        ok=bool(d.get("ok")),
        error=d.get("error"),
        source=str(d.get("source") or "gps"),
        fix_status=d.get("fix_status"),
        latitude=d.get("latitude"),
        longitude=d.get("longitude"),
        altitude=d.get("altitude"),
        accuracy=d.get("accuracy"),
        satellites=d.get("satellites"),
        speed=d.get("speed"),
        angle=d.get("angle"),
        timestamp=d.get("timestamp"),
        last_sentence=d.get("last_sentence"),
        age_s=d.get("age_s"),
        raw=d.get("raw"),
    )


async def _poll_loop() -> None:
    """Refresh _LATEST every POLL_INTERVAL_S until cancelled."""
    global _LATEST, _LATEST_RAW, _LAST_FETCH_OK_AT
    base = GPS_URL.rstrip("/")
    cur_url = f"{base}/gps/current"
    raw_url = f"{base}/gps/raw"
    log.info("gps poller targeting %s", base)
    while True:
        try:
            data = await asyncio.to_thread(_http_get_json, cur_url, HTTP_TIMEOUT_S)
            _LATEST = _fix_from_dict(data)
            _LAST_FETCH_OK_AT = time.time()
            try:
                _LATEST_RAW = await asyncio.to_thread(_http_get_json, raw_url, HTTP_TIMEOUT_S)
            except Exception as exc:
                _LATEST_RAW = {"error": f"raw fetch: {exc}"}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            age = time.time() - _LAST_FETCH_OK_AT if _LAST_FETCH_OK_AT else None
            _LATEST = _empty_fix(
                error=f"gps service unreachable: {exc}",
                source=f"poll {base}",
            )
            _LATEST.age_s = round(age, 3) if age is not None else None
            _LATEST_RAW = {"error": f"poll: {exc}"}
        except Exception as exc:
            log.warning("gps poll: unexpected error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_S)


async def start_listener() -> None:
    """Lifespan hook — start the background poller. Name kept for API
    compatibility with the previous in-process listener."""
    global _POLL_TASK, GPS_URL
    GPS_URL = os.environ.get("GPS_URL", DEFAULT_GPS_URL)
    _POLL_TASK = asyncio.create_task(_poll_loop())


async def stop_listener() -> None:
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
    from inside an async handler — never does I/O itself."""
    return _LATEST


# Async-compatible accessor matching the previous API shape.
async def fetch(host: str | None = None, timeout: float = 0.0) -> GpsFix:
    return current_fix()


# Stats accessor for /api/gps/raw — exposes whatever gps reports.
class _ListenerStub:
    """Compatibility shim so /api/gps/raw can do `listener.stats()`."""

    def stats(self) -> dict:
        return dict(_LATEST_RAW)


listener = _ListenerStub()
