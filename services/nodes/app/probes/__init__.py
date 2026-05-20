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

from . import edge_node as _edge_node
from . import middleware as _middleware
from . import service as _service
from . import tak_server as _tak_server

ProbeFn = Callable[[dict, dict], "Awaitable[dict]"]

REGISTRY: dict[str, ProbeFn] = {
    "edge-node":  _edge_node.probe,
    "middleware": _middleware.probe,
    "service":    _service.probe,
    "tak-server": _tak_server.probe,
}


def for_type(type_name: str) -> ProbeFn | None:
    return REGISTRY.get(type_name)
