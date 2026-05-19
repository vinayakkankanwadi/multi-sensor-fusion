"""Operator-facing controls for the TAK Server node.

Same shape as services/ui/app/{apex,bsi}/routes.py: one class, FastAPI
router as thin delegation.

  - state                Probes TCP :8443 (admin) and :8089 (streaming);
                         derives the WebTAK URL from the node entry so
                         the panel can iframe it.

Unlike the Apex / BSI panels, this one needs no server-side process and
no docker control. WebTAK is hosted by TAK Server itself; the operator's
browser presents the imported client cert directly to the iframe target.
The cert never touches our backend.
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..nodes import client as nodes_client

log = logging.getLogger(__name__)


class TAKController:

    NODE_ID = "tak-primary"

    async def _node(self) -> dict:
        payload = await nodes_client.fetch_current(type=None)
        for n in payload.get("nodes", []):
            if n.get("id") == self.NODE_ID:
                return n
        raise HTTPException(404, detail=f"node {self.NODE_ID!r} not found in registry")

    @staticmethod
    def _tcp_alive(host: str, port: int, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, socket.timeout):
            return False

    async def state(self) -> dict:
        """Liveness of admin (:8443) and streaming (:8089) + WebTAK URL."""
        n = await self._node()
        host        = n.get("host")
        admin_port  = int(n.get("admin_port") or 8443)
        stream_port = 8089  # convention; TAK Server SSL streaming

        admin_ok  = self._tcp_alive(host, admin_port)
        stream_ok = self._tcp_alive(host, stream_port)
        return {
            "available":   admin_ok or stream_ok,
            "host":        host,
            "admin_port":  admin_port,
            "admin_alive": admin_ok,
            "stream_port": stream_port,
            "stream_alive": stream_ok,
            "webtak_url":  f"https://{host}:{admin_port}/webtak/index.html",
        }


router = APIRouter(prefix="/api/tak", tags=["tak"])
_ctrl = TAKController()


@router.get("/state")
async def state() -> dict:
    return await _ctrl.state()
