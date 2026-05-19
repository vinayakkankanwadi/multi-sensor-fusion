"""Operator-facing controls for the Apex middleware node.

All Apex-related backend lives in one class, ``ApexController``, with the
FastAPI router as a thin delegation layer.

  - state                       quick health + currently-rolling archive file
  - gui_status / start / stop   lifecycle of the apex-gui compose service
  - sqlite_status / start / stop  lifecycle of the apex-sqlite-web compose
                                service (web-based SQLite browser)

Container control shells out to ``docker compose`` via the host's docker
socket (mounted into this container at /var/run/docker.sock). Project
root is mounted at /work so the compose file is resolvable.

Replay / archive listing intentionally not included here yet — separate
feature, separate add.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

log = logging.getLogger(__name__)


class ApexController:
    """All Apex operator-surface logic; one instance, used by the router."""

    ARCHIVE_DIR     = Path("/app/apex-archive")
    # Use the SAME absolute path the host uses (passed in via PROJECT_DIR
    # env from compose). compose-inside-container resolves bind-mount
    # paths against this, and the host daemon then finds the files where
    # the host put them. Fall back to a sane default for non-compose runs.
    PROJECT_DIR     = Path(os.environ.get("PROJECT_DIR", "/work"))
    APEX_GUI_SVC    = "apex-gui"
    APEX_SQLITE_SVC = "apex-sqlite-web"

    # ------ READ: archive --------------------------------------------------

    def _latest_db(self) -> Path | None:
        if not self.ARCHIVE_DIR.exists():
            return None
        dbs = sorted(self.ARCHIVE_DIR.glob("data-*.sqlite"))
        return dbs[-1] if dbs else None

    def state(self) -> dict:
        """One-glance status the operator panel renders."""
        db = self._latest_db()
        if not db:
            return {"available": False, "reason": "no archive files yet"}
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            msgs       = c.execute("SELECT COUNT(*) FROM Message").fetchone()[0]
            conns_open = c.execute(
                "SELECT COUNT(*) FROM Connection WHERE disconnect_time IS NULL"
            ).fetchone()[0]
            c.close()
        except sqlite3.Error as exc:
            return {"available": False, "reason": f"sqlite: {exc}", "file": db.name}
        return {
            "available": True,
            "file": db.name,
            "messages": msgs,
            "connections_open": conns_open,
        }

    # ------ docker compose helpers ----------------------------------------

    async def _compose(self, *args: str) -> tuple[int, str, str]:
        """Run `docker compose ...` against the host daemon. Returns
        (returncode, stdout, stderr)."""
        cmd = ["docker", "compose", "--project-directory", str(self.PROJECT_DIR),
               *args]
        log.info("apex/_compose: %s", " ".join(shlex.quote(c) for c in cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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

    # ------ GUI lifecycle --------------------------------------------------

    async def gui_status(self) -> dict:
        return {"running": await self._is_running(self.APEX_GUI_SVC)}

    async def gui_start(self) -> dict:
        # --force-recreate so the container always picks up the latest
        # compose config (e.g. updated bind paths, DISPLAY, image).
        rc, out, err = await self._compose(
            "--profile", "gui", "up", "-d", "--force-recreate", self.APEX_GUI_SVC,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"gui_start failed: {err or out}")
        return {"running": True}

    async def gui_stop(self) -> dict:
        # rm -fs (force, stop): stops AND removes — next start is clean,
        # no conflict on container name.
        rc, out, err = await self._compose(
            "--profile", "gui", "rm", "-fs", self.APEX_GUI_SVC,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"gui_stop failed: {err or out}")
        return {"running": False}

    # ------ SQLite-web lifecycle ------------------------------------------

    async def sqlite_status(self) -> dict:
        return {
            "running": await self._is_running(self.APEX_SQLITE_SVC),
            "url": "http://localhost:8095",
        }

    async def sqlite_start(self) -> dict:
        rc, out, err = await self._compose(
            "--profile", "sqlite-ui", "up", "-d", "--force-recreate",
            self.APEX_SQLITE_SVC,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"sqlite_start failed: {err or out}")
        return {"running": True, "url": "http://localhost:8095"}

    async def sqlite_stop(self) -> dict:
        rc, out, err = await self._compose(
            "--profile", "sqlite-ui", "rm", "-fs", self.APEX_SQLITE_SVC,
        )
        if rc != 0:
            raise HTTPException(500, detail=f"sqlite_stop failed: {err or out}")
        return {"running": False}


# ----------- Router (thin delegations) -------------------------------------

router = APIRouter(prefix="/api/apex", tags=["apex"])
_ctrl = ApexController()


@router.get("/state")
def state() -> dict:
    return _ctrl.state()


@router.get("/gui/status")
async def gui_status() -> dict:
    return await _ctrl.gui_status()


@router.post("/gui/start")
async def gui_start() -> dict:
    return await _ctrl.gui_start()


@router.post("/gui/stop")
async def gui_stop() -> dict:
    return await _ctrl.gui_stop()


@router.get("/sqlite/status")
async def sqlite_status() -> dict:
    return await _ctrl.sqlite_status()


@router.post("/sqlite/start")
async def sqlite_start() -> dict:
    return await _ctrl.sqlite_start()


@router.post("/sqlite/stop")
async def sqlite_stop() -> dict:
    return await _ctrl.sqlite_stop()
