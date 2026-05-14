"""msf-nodes — platform-node registry + per-service status aggregator.

A "node" is an upstream platform host (today: the LAN router) that
provides one or more services consumed by the rest of the stack — NTP
time, GPS NMEA push, and so on. This service holds the registry and
periodically asks the per-service owners (msf-ntp, msf-gps) what they
think; it then composes a per-node view so the UI can render one
green/yellow/red dot per node.

Owns nothing data-side; pure aggregator. Same shape as msf-middlewares.

Config: JSON array mounted at MSF_NODES_CONFIG (default
/app/config/nodes.json). Each entry: {id, name, host, services[], description}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .aggregator import aggregate

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("msf-nodes")

DEFAULT_CONFIG = "/app/config/nodes.json"
DEFAULT_INTERVAL_S = 10.0
DEFAULT_NTP_URL = "http://127.0.0.1:8091"
DEFAULT_GPS_URL = "http://127.0.0.1:8090"
HTTP_TIMEOUT_S = 1.5

_CONFIG_PATH = DEFAULT_CONFIG
_INTERVAL_S = DEFAULT_INTERVAL_S
_NTP_URL = DEFAULT_NTP_URL
_GPS_URL = DEFAULT_GPS_URL

_STATE: list[dict] = []
_CONFIG_ERROR: str | None = None
_LAST_REFRESH_AT: float = 0.0
_POLL_TASK: asyncio.Task | None = None


def _load_config() -> list[dict]:
    path = Path(_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"nodes config not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"nodes config invalid JSON: {exc}")
    if not isinstance(data, list):
        raise ValueError("nodes config must be a JSON array")
    seen: set[str] = set()
    for i, e in enumerate(data):
        if not isinstance(e, dict):
            raise ValueError(f"entry {i} is not an object")
        for f in ("id", "name", "host"):
            if f not in e:
                raise ValueError(f"entry {i} missing required field {f!r}")
        if e["id"] in seen:
            raise ValueError(f"duplicate id: {e['id']!r}")
        seen.add(e["id"])
        e.setdefault("services", [])
        e.setdefault("description", "")
    return data


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _fetch_upstreams() -> tuple[dict | None, dict | None]:
    """Pull msf-ntp's /ntp/sources and msf-gps's /gps/current in parallel.
    Returns (ntp_sources_or_None, gps_fix_or_None)."""
    async def _safe(url: str) -> dict | None:
        try:
            return await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
        except Exception as exc:
            log.warning("fetch %s: %s", url, exc)
            return None
    ntp, gps = await asyncio.gather(
        _safe(f"{_NTP_URL}/ntp/sources"),
        _safe(f"{_GPS_URL}/gps/current"),
    )
    return ntp, gps


async def _refresh_round() -> None:
    global _STATE, _CONFIG_ERROR, _LAST_REFRESH_AT
    try:
        entries = _load_config()
        _CONFIG_ERROR = None
    except Exception as exc:
        _CONFIG_ERROR = str(exc)
        log.warning("config load failed: %s", exc)
        return

    ntp_sources, gps_fix = await _fetch_upstreams()
    new_state = [aggregate(e, ntp_sources, gps_fix) for e in entries]
    _STATE = new_state
    _LAST_REFRESH_AT = time.time()
    summary = ", ".join(f"{n['id']}={n['severity']}" for n in _STATE)
    log.info("refreshed %d nodes: %s", len(_STATE), summary or "(none)")


async def _poll_loop() -> None:
    while True:
        try:
            await _refresh_round()
        except Exception as exc:
            log.warning("refresh round failed: %s", exc)
        await asyncio.sleep(_INTERVAL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _CONFIG_PATH, _INTERVAL_S, _NTP_URL, _GPS_URL, _POLL_TASK
    _CONFIG_PATH = os.environ.get("MSF_NODES_CONFIG", DEFAULT_CONFIG)
    _INTERVAL_S = float(os.environ.get("MSF_NODES_INTERVAL_S", DEFAULT_INTERVAL_S))
    _NTP_URL = os.environ.get("MSF_NTP_URL", DEFAULT_NTP_URL).rstrip("/")
    _GPS_URL = os.environ.get("MSF_GPS_URL", DEFAULT_GPS_URL).rstrip("/")
    log.info("msf-nodes starting: config=%s interval=%ss ntp=%s gps=%s",
             _CONFIG_PATH, _INTERVAL_S, _NTP_URL, _GPS_URL)
    try:
        await _refresh_round()
    except Exception as exc:
        log.warning("initial refresh failed: %s", exc)
    _POLL_TASK = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        if _POLL_TASK:
            _POLL_TASK.cancel()
            try:
                await _POLL_TASK
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(title="msf-nodes",
              version="1",
              description="Platform-node registry + per-service status aggregator (NTP / GPS / ...).",
              lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": _CONFIG_ERROR is None,
            "config_path": _CONFIG_PATH,
            "config_error": _CONFIG_ERROR,
            "interval_s": _INTERVAL_S,
            "ntp_url": _NTP_URL,
            "gps_url": _GPS_URL,
            "tracked": len(_STATE)}


@app.get("/nodes/current")
def current() -> dict:
    return {"config_error": _CONFIG_ERROR,
            "interval_s": _INTERVAL_S,
            "last_refresh_at": _LAST_REFRESH_AT or None,
            "nodes": list(_STATE)}


@app.get("/nodes/{node_id}")
def one(node_id: str) -> dict:
    for n in _STATE:
        if n["id"] == node_id:
            return n
    raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")
