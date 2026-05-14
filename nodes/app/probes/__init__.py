"""Probe-strategy registry.

Each strategy module exposes:
    async def probe(entry: dict, ctx: dict) -> dict
        Return a per-service status dict for one config entry. Returned
        shape is `{ok, severity, ... type-specific extras}`.

The orchestrator in `app.main` dispatches by `entry["type"]`; unknown
types get a synthetic "unknown" status so the UI can still render them.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from . import middleware as _middleware
from . import platform_node as _platform_node
from . import service as _service

ProbeFn = Callable[[dict, dict], "Awaitable[dict]"]

REGISTRY: dict[str, ProbeFn] = {
    "platform-node": _platform_node.probe,
    "middleware":    _middleware.probe,
    "service":       _service.probe,
}


def for_type(type_name: str) -> ProbeFn | None:
    return REGISTRY.get(type_name)
