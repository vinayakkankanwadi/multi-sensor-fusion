"""Middlewares accessor — thin HTTP client to the msf-middlewares service.

The registry + per-middleware TCP probes live in msf-middlewares. The UI
just asks `GET /middlewares/current` whenever it needs to render the
picker or look up the host:port for a selected middleware id.

Configure via:
    MSF_MIDDLEWARES_URL  base URL of the service
                         (default http://127.0.0.1:8092)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8092"
HTTP_TIMEOUT_S = 1.5


def _service_url() -> str:
    return os.environ.get("MSF_MIDDLEWARES_URL", DEFAULT_URL).rstrip("/")


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_current() -> dict:
    """Return the full payload from msf-middlewares (list + statuses)."""
    base = _service_url()
    url = f"{base}/middlewares/current"
    try:
        return await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"config_error": f"middlewares service unreachable: {exc}",
                "middlewares": []}
    except Exception as exc:
        return {"config_error": f"middlewares service error: {exc}",
                "middlewares": []}


def _http_patch_json(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="PATCH",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def patch_one(mw_id: str, *, host: str | None = None,
                    port: int | None = None) -> dict:
    """Update host/port for one middleware. The service persists the
    change to its mounted JSON config and re-probes immediately."""
    base = _service_url()
    body: dict = {}
    if host is not None:
        body["host"] = host
    if port is not None:
        body["port"] = port
    url = f"{base}/middlewares/{mw_id}"
    return await asyncio.to_thread(_http_patch_json, url, body, HTTP_TIMEOUT_S)
