"""nodes — unified registry + status service for every named resource on
the platform.

A *node* is anything the platform tracks: the LAN router (`platform-node`),
a SAPIENT middleware (`middleware`), a TAK Server (`tak-server`, future),
an edge / fusion node (`edge-node` / `fusion-node`, future). The shape is
the same for all of them — `{id, type, name, host, …, status, severity}`
— and each type plugs in its own probe strategy under `app.probes.*`.

This service replaces the older split into `nodes` (platform health)
and `middlewares` (SAPIENT endpoints). Both are now filtered views of
`GET /nodes/current?type=…`.

Config is a JSON array mounted at `NODES_CONFIG` (default
/app/config/nodes.json). Edits via `PATCH /nodes/{id}` are persisted back
to that file and the prober re-reads on the next round.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .probes import for_type

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("nodes")

DEFAULT_CONFIG = "/app/config/nodes.json"
DEFAULT_INTERVAL_S = 60.0   # gentle — see Apex/BSI receive-error history
DEFAULT_NTP_URL = "http://127.0.0.1:8091"
DEFAULT_GPS_URL = "http://127.0.0.1:8090"
HTTP_TIMEOUT_S = 1.5

_CONFIG_PATH = DEFAULT_CONFIG
_INTERVAL_S = DEFAULT_INTERVAL_S
_NTP_URL = DEFAULT_NTP_URL
_GPS_URL = DEFAULT_GPS_URL

# id → composed entry+status
_STATE: dict[str, dict] = {}
_CONFIG_ERROR: str | None = None
_LAST_REFRESH_AT: float = 0.0
_POLL_TASK: asyncio.Task | None = None


def _load_config() -> list[dict]:
    path = Path(_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"nodes config not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"nodes config invalid JSON: {exc}")
    if not isinstance(data, list):
        raise ValueError("nodes config must be a JSON array")
    seen: set[str] = set()
    for i, e in enumerate(data):
        if not isinstance(e, dict):
            raise ValueError(f"entry {i} is not an object")
        for f in ("id", "type", "name", "host"):
            if f not in e:
                raise ValueError(f"entry {i} missing required field {f!r}")
        if e["id"] in seen:
            raise ValueError(f"duplicate id: {e['id']!r}")
        seen.add(e["id"])
        e.setdefault("description", "")
    return data


def _save_config(entries: list[dict]) -> None:
    Path(_CONFIG_PATH).write_text(json.dumps(entries, indent=2) + "\n")


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _fetch_context() -> dict:
    """Pre-fetch the upstreams platform-node probes need, in parallel.
    Returns a dict the probe modules can pull from."""
    async def _safe(url: str) -> dict | None:
        try:
            return await asyncio.to_thread(_http_get_json, url, HTTP_TIMEOUT_S)
        except Exception as exc:
            log.warning("fetch %s: %s", url, exc)
            return None
    ntp, gps = await asyncio.gather(
        _safe(f"{_NTP_URL}/ntp/sources"),
        _safe(f"{_GPS_URL}/gps/current"),
    )
    return {"ntp_sources": ntp, "gps_fix": gps}


async def _refresh_round() -> None:
    global _CONFIG_ERROR, _LAST_REFRESH_AT
    try:
        entries = _load_config()
        _CONFIG_ERROR = None
    except Exception as exc:
        _CONFIG_ERROR = str(exc)
        log.warning("config load failed: %s", exc)
        return

    ctx = await _fetch_context()
    now = time.time()
    new_state: dict[str, dict] = {}
    for entry in entries:
        type_name = entry["type"]
        probe_fn = for_type(type_name)
        prev = _STATE.get(entry["id"], {})
        if probe_fn is None:
            extras = {
                "severity": "unknown",
                "ok": False,
                "status": {"ok": False, "severity": "unknown",
                           "error": f"no probe registered for type {type_name!r}"},
            }
        else:
            try:
                extras = await probe_fn(entry, ctx)
            except Exception as exc:
                log.warning("probe %s (%s) failed: %s", entry["id"], type_name, exc)
                extras = {
                    "severity": "fail",
                    "ok": False,
                    "status": {"ok": False, "severity": "fail",
                               "error": f"probe error: {exc}"},
                }

        composed = dict(entry)
        composed.update(extras)
        composed["last_probed_at"] = now
        composed["last_ok_at"] = now if extras.get("ok") else prev.get("last_ok_at")
        composed["first_seen_at"] = prev.get("first_seen_at") or now
        new_state[entry["id"]] = composed

    _STATE.clear()
    _STATE.update(new_state)
    _LAST_REFRESH_AT = now
    summary = ", ".join(f"{n['id']}={n['severity']}" for n in _STATE.values())
    log.info("refreshed %d nodes: %s", len(_STATE), summary or "(none)")


async def _poll_loop() -> None:
    while True:
        try:
            await _refresh_round()
        except Exception as exc:
            log.warning("refresh round failed: %s", exc)
        await asyncio.sleep(_INTERVAL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _CONFIG_PATH, _INTERVAL_S, _NTP_URL, _GPS_URL, _POLL_TASK
    _CONFIG_PATH = os.environ.get("NODES_CONFIG", DEFAULT_CONFIG)
    _INTERVAL_S = float(os.environ.get("NODES_INTERVAL_S", DEFAULT_INTERVAL_S))
    _NTP_URL = os.environ.get("NTP_URL", DEFAULT_NTP_URL).rstrip("/")
    _GPS_URL = os.environ.get("GPS_URL", DEFAULT_GPS_URL).rstrip("/")
    log.info("nodes starting: config=%s interval=%ss ntp=%s gps=%s",
             _CONFIG_PATH, _INTERVAL_S, _NTP_URL, _GPS_URL)
    try:
        await _refresh_round()
    except Exception as exc:
        log.warning("initial refresh failed: %s", exc)
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


app = FastAPI(title="nodes",
              version="1",
              description="Unified registry + status for every platform resource (platform-node, middleware, …).",
              lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": _CONFIG_ERROR is None,
            "config_path": _CONFIG_PATH,
            "config_error": _CONFIG_ERROR,
            "interval_s": _INTERVAL_S,
            "ntp_url": _NTP_URL,
            "gps_url": _GPS_URL,
            "tracked": len(_STATE)}


@app.get("/nodes/current")
def current(type: str | None = None) -> dict:
    """Latest known status for every node. `?type=…` filters the result —
    used by the UI's two drawers to render only platform-nodes or only
    middleware entries from the same source of truth."""
    items = list(_STATE.values())
    if type:
        items = [n for n in items if n.get("type") == type]
    return {"config_error": _CONFIG_ERROR,
            "interval_s": _INTERVAL_S,
            "last_refresh_at": _LAST_REFRESH_AT or None,
            "nodes": items}


@app.get("/nodes/{node_id}")
def one(node_id: str) -> dict:
    if node_id not in _STATE:
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")
    return _STATE[node_id]


import re

# Known types: every entry's `type` must be one of these. Adding a new
# type means adding a probe module under app/probes/ and registering it
# in app/probes/__init__.py.
KNOWN_TYPES = {"platform-node", "middleware", "service", "tak-server"}

# id must be DNS-label-safe so we can use it in URL paths without
# escaping. Same character set as a docker container name.
_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_id(node_id: str) -> None:
    if not _ID_RE.match(node_id):
        raise HTTPException(
            status_code=400,
            detail=f"invalid id {node_id!r}: must be alphanumeric, dash, "
                   "underscore; 1–64 chars; can't start with -/_",
        )


def _validate_type_specific(entry: dict) -> None:
    """Each type has its own required-fields contract. Surface clear errors
    instead of letting the probe layer fail mysteriously later."""
    t = entry.get("type")
    if t not in KNOWN_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown type {t!r}; must be one of {sorted(KNOWN_TYPES)}",
        )
    if t == "platform-node":
        services = entry.get("services") or []
        if not isinstance(services, list):
            raise HTTPException(status_code=400, detail="services must be a list")
        unknown = [s for s in services if s not in ("ntp", "gps")]
        if unknown:
            raise HTTPException(status_code=400,
                                detail=f"unknown platform-node services: {unknown}")
    elif t == "middleware":
        if "port" not in entry:
            raise HTTPException(status_code=400, detail="middleware requires port")
    elif t == "service":
        if "port" not in entry:
            raise HTTPException(status_code=400, detail="service requires port")
        if "health_path" not in entry and entry.get("probe_kind") != "tcp":
            raise HTTPException(
                status_code=400,
                detail="service requires either health_path (HTTP probe) "
                       "or probe_kind=\"tcp\"",
            )
    elif t == "tak-server":
        if "port" not in entry:
            raise HTTPException(status_code=400, detail="tak-server requires port")
        # Optional probe_kind=tcp + admin_port — validate the combo when set.
        if entry.get("probe_kind") == "tcp" and "admin_port" not in entry:
            raise HTTPException(
                status_code=400,
                detail="tak-server with probe_kind=tcp needs admin_port "
                       "(TCP admin port, e.g. 8089) — the CoT port itself is UDP",
            )


# ---------------------------------------------------------------- POST

class NodeCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    host: str = Field(..., min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    # Optional per-type extras — backend validates the right combo per type.
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    admin_port: int | None = Field(None, ge=1, le=65535)
    protocol: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


@app.post("/nodes", status_code=201)
async def create_node(req: NodeCreate) -> dict:
    """Create a new node entry. `id` and `type` are immutable post-create
    (changing them in flight would break probe dispatch + status keying).
    Persists to the mounted JSON config and re-probes immediately."""
    _validate_id(req.id)

    try:
        entries = _load_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"config: {exc}")

    if any(e["id"] == req.id for e in entries):
        raise HTTPException(status_code=409,
                            detail=f"node {req.id!r} already exists")

    new_entry = req.model_dump(exclude_none=True)
    new_entry.setdefault("description", "")
    _validate_type_specific(new_entry)

    entries.append(new_entry)
    try:
        _save_config(entries)
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"write config: {exc} (is the volume rw?)")

    await _refresh_round()
    return _STATE.get(req.id, {})


# ---------------------------------------------------------------- DELETE

@app.delete("/nodes/{node_id}", status_code=200)
async def delete_node(node_id: str) -> dict:
    """Delete a node from the config. Re-probes immediately so the state
    cache is consistent. Idempotent — returns 404 if the id is unknown."""
    try:
        entries = _load_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"config: {exc}")

    target = next((e for e in entries if e["id"] == node_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")

    entries = [e for e in entries if e["id"] != node_id]
    try:
        _save_config(entries)
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"write config: {exc} (is the volume rw?)")

    await _refresh_round()
    return {"removed": node_id}


# ---------------------------------------------------------------- PATCH

class NodePatch(BaseModel):
    # `id` and `type` deliberately absent — immutable post-create.
    name: str | None = Field(None, min_length=1, max_length=128)
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    admin_port: int | None = Field(None, ge=1, le=65535)
    protocol: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


@app.patch("/nodes/{node_id}")
async def patch_one(node_id: str, req: NodePatch) -> dict:
    """Edit any field on an existing node *except* its id or type. Persists
    to the mounted JSON config and re-probes immediately. Type-specific
    validation runs again after the merge — illegal combinations (e.g.
    a service without health_path or probe_kind) get rejected."""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail="provide at least one field to update",
        )

    try:
        entries = _load_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"config: {exc}")

    target = next((e for e in entries if e["id"] == node_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")

    merged = {**target, **updates}
    # host gets whitespace-stripped (common copy/paste hazard).
    if "host" in updates:
        merged["host"] = str(merged["host"]).strip()
    _validate_type_specific(merged)
    # Write merged values back onto the original dict (preserves field order).
    target.update(merged)

    try:
        _save_config(entries)
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"write config: {exc} (is the volume rw?)")

    await _refresh_round()
    return _STATE.get(node_id, {})
