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


def _http_send_json(url: str, body: dict, method: str, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body.decode("utf-8")) if body else {}


def _http_patch_json(url: str, body: dict, timeout: float) -> dict:
    return _http_send_json(url, body, "PATCH", timeout)


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


async def patch_one(node_id: str, body: dict) -> dict:
    """PATCH the given fields on one node. Service validates per-type
    and re-probes immediately. `id` and `type` are immutable and ignored
    by the backend PATCH model."""
    base = _service_url()
    url = f"{base}/nodes/{node_id}"
    return await asyncio.to_thread(_http_patch_json, url, body, HTTP_TIMEOUT_S)


async def create(body: dict) -> dict:
    """POST a new node entry. Service validates id is unique, type is
    known, and type-specific required fields are present."""
    base = _service_url()
    url = f"{base}/nodes"
    return await asyncio.to_thread(_http_send_json, url, body, "POST", HTTP_TIMEOUT_S)


async def delete(node_id: str) -> dict:
    """DELETE a node from the config. 404 if id unknown."""
    base = _service_url()
    url = f"{base}/nodes/{node_id}"
    return await asyncio.to_thread(_http_send_json, url, None, "DELETE", HTTP_TIMEOUT_S)
