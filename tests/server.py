"""HTTP wrapper around the regression suite.

Long-running FastAPI app inside the regression image. Endpoints:

    GET  /health   200 + current run state (always non-blocking)
    POST /run      kick off pytest in the background; returns the new run_id.
                   400 if a run is already in progress.
    GET  /status   the current state of the most recent run
    GET  /result   the structured per-file summary written by
                   tests/conftest.py's pytest_terminal_summary hook

This exists so the UI can offer a "Run tests" button + show coloured
per-file results without anyone needing to drop to a shell. The CLI
workflow (`docker compose exec regression pytest /work/tests`) keeps
working too.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException


RESULT_JSON = Path("/tmp/last_run.json")
PYTEST_CMD = [
    "pytest", "--tb=short", "-p", "no:cacheprovider", "--color=no",
    "-c", "/work/tests/pytest.ini", "/work/tests",
]

app = FastAPI(title="regression-runner")

_state: dict[str, Any] = {
    "status": "idle",           # idle | running | done
    "run_id": None,
    "started_at": None,
    "ended_at": None,
    "duration_s": None,
    "exit_code": None,
    "tail": "",                 # last ~4KB of pytest stdout
}
_lock = asyncio.Lock()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "status": _state["status"]}


@app.get("/status")
def status() -> dict:
    return dict(_state)


@app.get("/result")
def result() -> dict:
    """Per-file structured summary from the last completed run."""
    if not RESULT_JSON.exists():
        return {"available": False, "state": dict(_state)}
    try:
        payload = json.loads(RESULT_JSON.read_text())
    except Exception as exc:
        raise HTTPException(500, f"could not read {RESULT_JSON}: {exc}")
    payload["available"] = True
    payload["state"] = dict(_state)
    return payload


@app.post("/run")
async def run() -> dict:
    if _state["status"] == "running":
        raise HTTPException(409, "a run is already in progress")
    run_id = f"{int(time.time())}-{os.urandom(2).hex()}"
    _state.update(
        status="running", run_id=run_id,
        started_at=time.time(), ended_at=None, duration_s=None,
        exit_code=None, tail="",
    )
    # Remove stale result so polling clients don't see the previous run's data.
    try:
        RESULT_JSON.unlink()
    except FileNotFoundError:
        pass
    asyncio.create_task(_run_pytest(run_id))
    return dict(_state)


async def _run_pytest(run_id: str) -> None:
    async with _lock:
        try:
            proc = await asyncio.create_subprocess_exec(
                *PYTEST_CMD,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout_bytes, _ = await proc.communicate()
            _state["exit_code"] = proc.returncode
            _state["tail"] = stdout_bytes[-4096:].decode("utf-8", errors="replace")
        except Exception as exc:
            _state["exit_code"] = -1
            _state["tail"] = f"runner error: {exc}"
        finally:
            _state["ended_at"] = time.time()
            _state["duration_s"] = round(_state["ended_at"] - _state["started_at"], 2)
            _state["status"] = "done"
