"""Nodes accessor — thin HTTP client to the unified `nodes` service.

The platform-resource registry (every named host: router, SAPIENT
middlewares, future TAK servers / edge / fusion nodes) lives in one
service now. The UI asks `GET /nodes/current?type=…` for filtered views;
the previous split into msf-nodes + msf-middlewares has been retired.

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


def _http_patch_json(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="PATCH",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_current(type: str | None = None) -> dict:
    """Return `/nodes/current[?type=…]`. Used by the UI's Nodes and
    Middleware drawers (filtered views of the same source of truth)."""
    base = _service_url()
    qs = f"?type={type}" if type else ""
    url = f"{base}/nodes/current{qs}"
    try:
        return await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"config_error": f"nodes service unreachable: {exc}", "nodes": []}
    except Exception as exc:
        return {"config_error": f"nodes service error: {exc}", "nodes": []}


async def patch_one(node_id: str, *, host: str | None = None,
                    port: int | None = None,
                    probe: bool | None = None) -> dict:
    """PATCH `host` / `port` / `probe` on one node. The service writes
    the change to the mounted config and re-probes immediately."""
    base = _service_url()
    body: dict = {}
    if host is not None: body["host"] = host
    if port is not None: body["port"] = port
    if probe is not None: body["probe"] = probe
    url = f"{base}/nodes/{node_id}"
    return await asyncio.to_thread(_http_patch_json, url, body, HTTP_TIMEOUT_S)
