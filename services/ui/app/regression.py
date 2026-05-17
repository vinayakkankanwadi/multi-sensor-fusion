"""Regression accessor — thin HTTP client to the `regression` service.

Long-running pytest runner exposes /run, /status, /result on
http://127.0.0.1:8094 (configurable via REGRESSION_URL). The UI's Tests
drawer proxies through these.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8094"
HTTP_TIMEOUT_S = 2.5


def _service_url() -> str:
    return os.environ.get("REGRESSION_URL", DEFAULT_URL).rstrip("/")


def _request(path: str, method: str = "GET", timeout: float = HTTP_TIMEOUT_S) -> dict:
    url = f"{_service_url()}{path}"
    data = b"" if method == "POST" else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body.decode("utf-8")) if body else {}
    except urllib.error.HTTPError as exc:
        # Surface server-side errors (e.g. 409 if a run is already in progress)
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"detail": exc.reason}
        payload["__status_code"] = exc.code
        return payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": str(exc), "__status_code": 503}


async def status() -> dict:
    return await asyncio.to_thread(_request, "/status")


async def result() -> dict:
    return await asyncio.to_thread(_request, "/result")


async def run() -> dict:
    return await asyncio.to_thread(_request, "/run", "POST", 5.0)
