"""msf-middlewares — registry + status prober for SAPIENT middlewares.

Reads a list of known middlewares from a mounted JSON config and
TCP-probes each one on a fixed cadence. Exposes:

    GET /middlewares/current   list + live status for each
    GET /middlewares/{id}      one middleware's config + status
    GET /health                liveness

The UI (and any future consumer — dashboards, fusion node health
indicators, etc.) reads this service over HTTP. The probe cadence is
centralised here so the upstream endpoints aren't hammered by every
consumer doing its own check.

The config file is re-read on every probe round, so adding or editing
an entry just requires saving the JSON file — no container restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .prober import probe

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("msf-middlewares")

DEFAULT_CONFIG = "/app/config/middlewares.json"
DEFAULT_INTERVAL_S = 10.0
DEFAULT_TIMEOUT_S = 1.5
DEFAULT_WARN_AFTER_S = 0.5

_CONFIG_PATH: str = DEFAULT_CONFIG
_INTERVAL_S: float = DEFAULT_INTERVAL_S
_TIMEOUT_S: float = DEFAULT_TIMEOUT_S
_WARN_AFTER_S: float = DEFAULT_WARN_AFTER_S

# Current state: { id: {config..., status: {...}, last_probed_at, last_ok_at} }
_STATE: dict[str, dict] = {}
_CONFIG_ERROR: str | None = None

_POLL_TASK: asyncio.Task | None = None


def _load_config() -> list[dict]:
    """Read the middlewares.json file; raise on malformed input."""
    path = Path(_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"middlewares config not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"middlewares config invalid JSON: {exc}")
    if not isinstance(data, list):
        raise ValueError("middlewares config must be a JSON array")
    seen_ids: set[str] = set()
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"entry {i} is not an object")
        for field in ("id", "name", "host", "port"):
            if field not in entry:
                raise ValueError(f"entry {i} missing required field '{field}'")
        if entry["id"] in seen_ids:
            raise ValueError(f"duplicate id: {entry['id']!r}")
        seen_ids.add(entry["id"])
        entry.setdefault("kind", "unknown")
        entry.setdefault("description", "")
        entry.setdefault("probe", True)
    return data


_NOT_PROBED_STATUS = {
    "ok": False,
    "severity": "unknown",
    "rtt_s": None,
    "error": "probing disabled in config",
}


async def _probe_round() -> None:
    global _CONFIG_ERROR
    try:
        entries = _load_config()
        _CONFIG_ERROR = None
    except Exception as exc:
        _CONFIG_ERROR = str(exc)
        log.warning("config load failed: %s", exc)
        return

    # Probe entries with probe=true; emit a synthetic "not probed" status
    # for the rest so the UI can still render them. Skipping the TCP
    # connect entirely matters because every probe round is logged as a
    # receiver error by the SAPIENT middleware on the other end.
    to_probe = [e for e in entries if e.get("probe", True)]
    probe_results = await asyncio.gather(
        *[probe(e["host"], int(e["port"]),
                timeout_s=_TIMEOUT_S,
                warn_after_s=_WARN_AFTER_S) for e in to_probe]
    )
    probed_by_id = {e["id"]: r for e, r in zip(to_probe, probe_results)}

    now = time.time()
    new_state: dict[str, dict] = {}
    for entry in entries:
        prev = _STATE.get(entry["id"], {})
        probed = entry["id"] in probed_by_id
        status = (probed_by_id[entry["id"]].to_dict() if probed
                  else dict(_NOT_PROBED_STATUS))
        new_state[entry["id"]] = {
            "id": entry["id"],
            "name": entry["name"],
            "host": entry["host"],
            "port": int(entry["port"]),
            "kind": entry["kind"],
            "probe": bool(entry.get("probe", True)),
            "description": entry["description"],
            "status": status,
            "last_probed_at": now if probed else prev.get("last_probed_at"),
            "last_ok_at": now if (probed and status["ok"]) else prev.get("last_ok_at"),
            "first_seen_at": prev.get("first_seen_at") or now,
        }
    _STATE.clear()
    _STATE.update(new_state)
    ok = sum(1 for s in _STATE.values() if s["status"]["ok"])
    skipped = len(entries) - len(to_probe)
    log.info("probed %d middlewares: %d ok, %d skipped",
             len(to_probe), ok, skipped)


async def _poll_loop() -> None:
    while True:
        try:
            await _probe_round()
        except Exception as exc:
            log.warning("probe round failed: %s", exc)
        await asyncio.sleep(_INTERVAL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _CONFIG_PATH, _INTERVAL_S, _TIMEOUT_S, _WARN_AFTER_S, _POLL_TASK
    _CONFIG_PATH = os.environ.get("MSF_MIDDLEWARES_CONFIG", DEFAULT_CONFIG)
    _INTERVAL_S = float(os.environ.get("MSF_MIDDLEWARES_INTERVAL_S", DEFAULT_INTERVAL_S))
    _TIMEOUT_S = float(os.environ.get("MSF_MIDDLEWARES_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    _WARN_AFTER_S = float(os.environ.get("MSF_MIDDLEWARES_WARN_AFTER_S", DEFAULT_WARN_AFTER_S))
    log.info("msf-middlewares starting: config=%s interval=%ss timeout=%ss",
             _CONFIG_PATH, _INTERVAL_S, _TIMEOUT_S)
    try:
        await _probe_round()
    except Exception as exc:
        log.warning("initial probe failed: %s", exc)
    _POLL_TASK = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        if _POLL_TASK:
            _POLL_TASK.cancel()
            try:
                await _POLL_TASK
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(title="msf-middlewares",
              version="1",
              description="Registry + status prober for SAPIENT middlewares.",
              lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": _CONFIG_ERROR is None,
            "config_path": _CONFIG_PATH,
            "config_error": _CONFIG_ERROR,
            "interval_s": _INTERVAL_S,
            "tracked": len(_STATE)}


@app.get("/middlewares/current")
def current() -> dict:
    """List of every configured middleware + its current status."""
    return {
        "config_error": _CONFIG_ERROR,
        "interval_s": _INTERVAL_S,
        "middlewares": list(_STATE.values()),
    }


@app.get("/middlewares/{mw_id}")
def one(mw_id: str) -> dict:
    if mw_id not in _STATE:
        raise HTTPException(status_code=404, detail=f"unknown middleware: {mw_id}")
    return _STATE[mw_id]


class PatchRequest(BaseModel):
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)


@app.patch("/middlewares/{mw_id}")
async def patch_one(mw_id: str, req: PatchRequest) -> dict:
    """Edit host/port of one middleware. Rewrites the mounted JSON config
    so the change persists across container restarts, then triggers an
    immediate re-probe so the UI sees the new status on the next poll."""
    if req.host is None and req.port is None:
        raise HTTPException(status_code=400,
                            detail="provide at least one of host, port")
    try:
        entries = _load_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"config: {exc}")

    target = next((e for e in entries if e["id"] == mw_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"unknown middleware: {mw_id}")

    if req.host is not None:
        target["host"] = req.host.strip()
    if req.port is not None:
        target["port"] = int(req.port)

    try:
        Path(_CONFIG_PATH).write_text(json.dumps(entries, indent=2) + "\n")
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"write config: {exc} (is the volume rw?)")

    # Re-probe immediately so the caller doesn't have to wait for the
    # next scheduled round.
    await _probe_round()
    return _STATE.get(mw_id, {})
