"""Nodes accessor — thin HTTP client to the msf-nodes service.

The platform-node registry (and per-service aggregation) lives in
msf-nodes; the UI just asks `GET /nodes/current` whenever it wants to
render the picker.

Configure via:
    MSF_NODES_URL  base URL of the service (default http://127.0.0.1:8093)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8093"
HTTP_TIMEOUT_S = 1.5


def _service_url() -> str:
    return os.environ.get("MSF_NODES_URL", DEFAULT_URL).rstrip("/")


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_current() -> dict:
    base = _service_url()
    url = f"{base}/nodes/current"
    try:
        return await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"config_error": f"nodes service unreachable: {exc}",
                "nodes": []}
    except Exception as exc:
        return {"config_error": f"nodes service error: {exc}",
                "nodes": []}
