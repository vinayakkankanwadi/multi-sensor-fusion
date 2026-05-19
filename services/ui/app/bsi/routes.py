"""Operator-facing controls for the BSI Windows node.

Same shape as services/ui/app/apex/routes.py: one class, FastAPI router as
thin delegation. For BSI:

  - state                       Postgres reachability + identity
  - pgweb_status / start / stop  lifecycle of the bsi-pgweb compose
                                service (web-based Postgres browser)

Container control shells out to ``docker compose`` against the host's
docker daemon (mounted into this container at /var/run/docker.sock).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import socket
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..nodes import client as nodes_client

log = logging.getLogger(__name__)


class BSIController:
    """All BSI operator-surface logic; one instance, used by the router."""

    PROJECT_DIR = Path(os.environ.get("PROJECT_DIR", "/work"))
    NODE_ID     = "bsi-windows"
    PGWEB_SVC   = "bsi-pgweb"
    PGWEB_URL   = "http://localhost:8096"

    # ------ Read live node config from the nodes service ------------------

    async def _node(self) -> dict:
        """Pull the bsi-windows entry from the nodes service registry.
        Source of truth for host/port/db credentials — operator edits via
        the UI's node form land here without a restart."""
        payload = await nodes_client.fetch_current(type=None)
        for n in payload.get("nodes", []):
            if n.get("id") == self.NODE_ID:
                return n
        raise HTTPException(404, detail=f"node {self.NODE_ID!r} not found in registry")

    # ------ Reachability --------------------------------------------------

    async def state(self) -> dict:
        """One-glance: is BSI's Postgres reachable on the LAN?"""
        n = await self._node()
        host = n.get("host")
        port = int(n.get("port") or 5432)
        try:
            with socket.create_connection((host, port), timeout=1.5):
                pass
        except (OSError, socket.timeout) as exc:
            return {
                "available": False,
                "host": host, "port": port,
                "reason": str(exc) or "timeout",
            }
        return {
            "available": True,
            "host": host, "port": port,
            "database": n.get("db_database"),
        }

    # ------ docker compose helpers ----------------------------------------

    async def _compose(self, *args: str, env_overrides: dict | None = None) -> tuple[int, str, str]:
        cmd = ["docker", "compose", "--project-directory", str(self.PROJECT_DIR),
               *args]
        log.info("bsi/_compose: %s", " ".join(shlex.quote(c) for c in cmd))
        env = os.environ.copy()
        if env_overrides:
            env.update({k: str(v) for k, v in env_overrides.items() if v is not None})
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")

    async def _is_running(self, container_name: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Running}}", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return proc.returncode == 0 and out.decode().strip() == "true"

    # ------ pgweb lifecycle -----------------------------------------------

    async def pgweb_status(self) -> dict:
        return {
            "running": await self._is_running(self.PGWEB_SVC),
            "url": self.PGWEB_URL,
        }

    async def pgweb_start(self) -> dict:
        # Pull live creds from the node registry — operator can edit them
        # in the UI form and the very next click here picks up the change.
        n = await self._node()
        env_overrides = {
            "BSI_HOST":    n.get("host"),
            "BSI_PG_PORT": n.get("port") or 5432,
            "BSI_PG_USER": n.get("db_user")     or "postgres",
            "BSI_PG_PASS": n.get("db_password") or "password",
            "BSI_PG_DB":   n.get("db_database") or "sapientBSIFlex335v2",
        }
        rc, out, err = await self._compose(
            "--profile", "bsi-db", "up", "-d", "--force-recreate", self.PGWEB_SVC,
            env_overrides=env_overrides,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"pgweb_start failed: {err or out}")
        return {"running": True, "url": self.PGWEB_URL}

    async def pgweb_stop(self) -> dict:
        rc, out, err = await self._compose(
            "--profile", "bsi-db", "rm", "-fs", self.PGWEB_SVC,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"pgweb_stop failed: {err or out}")
        return {"running": False}


# ----------- Router (thin delegations) -------------------------------------

router = APIRouter(prefix="/api/bsi", tags=["bsi"])
_ctrl = BSIController()


@router.get("/state")
async def state() -> dict:
    return await _ctrl.state()


@router.get("/pgweb/status")
async def pgweb_status() -> dict:
    return await _ctrl.pgweb_status()


@router.post("/pgweb/start")
async def pgweb_start() -> dict:
    return await _ctrl.pgweb_start()


@router.post("/pgweb/stop")
async def pgweb_stop() -> dict:
    return await _ctrl.pgweb_stop()
