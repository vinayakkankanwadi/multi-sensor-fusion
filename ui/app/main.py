"""FastAPI entrypoint for the UI.

Endpoints:
  GET  /                              single-page UI
  GET  /api/health                    liveness + template names
  GET  /api/templates                 discovered templates with raw + decoded preview
  GET  /api/templates/{name}          one template's raw JSON
  POST /api/templates/regenerate      run proto-to-template converter against /app/templates
  POST /api/send                      send one templated message; capture transcript
  GET  /api/runs                      list recent run summaries
  GET  /api/runs/{run_id}             one run's full transcript
  GET  /api/ntp                       probe NTP server and return offset/severity
  GET  /api/validate                  client-side validate a template (no send)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import clocks, flow, gps, nodes, ntp, proto_to_template, runner, templates_loader, validators

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await gps.start_listener()
    log.info("startup complete")
    try:
        yield
    finally:
        await gps.stop_listener()


app = FastAPI(title="msf-ui",
              version="3",
              description="Send any SAPIENT BSI Flex 335 v2 templated message to a configurable endpoint.",
              lifespan=_lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    # no-cache the shell so cache-busted /static/*?v=… queries are seen
    # immediately after a UI deploy (otherwise the browser keeps the old
    # script tag with the old version string).
    return FileResponse(STATIC_DIR / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def api_health() -> dict:
    return {"ok": True,
            "templates": [t["name"] for t in templates_loader.list_templates()]}


# --- Templates --------------------------------------------------------------

@app.get("/api/templates")
def api_list_templates() -> list[dict]:
    return templates_loader.list_templates()


@app.get("/api/templates/{name}")
def api_get_template(name: str) -> dict:
    try:
        return {"name": name, "raw": templates_loader.get_template(name)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class RegenRequest(BaseModel):
    out_dir: str | None = None


@app.delete("/api/templates")
def api_clear_templates() -> dict:
    """Delete every .json under templates/. Sidebar goes empty; the user
    can re-populate via `POST /api/templates/regenerate` (UI "Build from
    .proto") or by dropping a .json into the mounted templates/ volume."""
    out_dir = Path(templates_loader.TEMPLATES_DIR)
    removed: list[str] = []
    if out_dir.exists():
        for p in out_dir.glob("*.json"):
            try:
                p.unlink()
                removed.append(p.name)
            except OSError as exc:
                log.warning("could not remove %s: %s", p, exc)
    return {"removed": removed, "count": len(removed)}


@app.post("/api/templates/regenerate")
def api_regenerate_templates(req: RegenRequest | None = None) -> dict:
    out = Path((req.out_dir if req else None) or templates_loader.TEMPLATES_DIR)
    written = proto_to_template.regenerate_all(out)
    return {"out_dir": str(out), "written": written, "count": len(written)}


# --- Validation -------------------------------------------------------------

class ValidateRequest(BaseModel):
    node_id: str
    template_name: str | None = None
    raw_json: str | None = None


@app.post("/api/validate")
def api_validate(req: ValidateRequest) -> dict:
    """Run the client-side validator against a rendered template."""
    try:
        text = req.raw_json if req.raw_json is not None else templates_loader.get_template(req.template_name)
        message = templates_loader.render(text, node_id=req.node_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        return {"ok": False, "errors": [f"render: {exc}"]}
    errors = validators.validate(message)
    return {"ok": not errors, "errors": errors,
            "content": message.WhichOneof("content")}


# --- Send -------------------------------------------------------------------

class SendRequest(BaseModel):
    host: str = Field(..., min_length=1, description="Target IP or hostname (non-empty)")
    port: int = Field(..., ge=1, le=65535)
    node_id: str = Field(..., description="UUID node_id used for {{NODE_ID}}")
    template_name: str = Field(..., description="Template stem")
    raw_json: str | None = Field(None, description="UI-edited override of the template body")
    recv_timeout_s: float = Field(5.0, ge=0.0, le=60.0)
    drain_after_s: float = Field(1.0, ge=0.0, le=60.0)
    validate_before_send: bool = Field(False,
        description="If true, run the client-side validator and refuse to send on failure")


@app.post("/api/send")
async def api_send(req: SendRequest) -> dict:
    host = (req.host or "").strip()
    if not host:
        raise HTTPException(status_code=400,
                            detail="host is required (set Host in the top bar before clicking Send)")
    try:
        text = req.raw_json if req.raw_json is not None else templates_loader.get_template(req.template_name)
        message = templates_loader.render(text, node_id=req.node_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"render: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"template parse failed: {exc}")

    validation_errors: list[str] = []
    if req.validate_before_send:
        validation_errors = validators.validate(message)
        if validation_errors:
            return {
                "run_id": None,
                "host": req.host,
                "port": req.port,
                "template": req.template_name,
                "error": "validation failed (client-side); not sent",
                "validation_errors": validation_errors,
                "transcript": [],
            }

    payload = message.SerializeToString()
    decoded = templates_loader.message_to_dict(message)
    decoded["_content"] = message.WhichOneof("content")

    result = await runner.send_one(
        host=host,
        port=req.port,
        payload=payload,
        template_name=req.template_name,
        decoded_sent=decoded,
        recv_timeout_s=req.recv_timeout_s,
        drain_after_s=req.drain_after_s,
    )
    result["validation_errors"] = validation_errors

    return result


# --- Flow (multi-step over a single TCP connection) -------------------------

class FlowStep(BaseModel):
    template_name: str
    raw_json: str | None = None
    wait_for: str | None = None
    recv_timeout_s: float = Field(5.0, ge=0.0, le=60.0)
    drain_after_s: float = Field(0.5, ge=0.0, le=60.0)
    gap_before_s: float = Field(0.0, ge=0.0, le=30.0)


class FlowRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    node_id: str
    steps: list[FlowStep]
    validate_before_send: bool = False


@app.post("/api/send_flow")
async def api_send_flow(req: FlowRequest) -> dict:
    if not req.steps:
        raise HTTPException(status_code=400, detail="flow needs at least one step")
    steps = [
        flow.Step(
            template_name=s.template_name,
            raw_json=s.raw_json,
            wait_for=s.wait_for,
            recv_timeout_s=s.recv_timeout_s,
            drain_after_s=s.drain_after_s,
            gap_before_s=s.gap_before_s,
        ) for s in req.steps
    ]
    try:
        return await flow.run_flow(
            host=req.host.strip(), port=req.port, node_id=req.node_id,
            steps=steps, validate_before_send=req.validate_before_send,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- Runs -------------------------------------------------------------------

def _summarise_message(msg: dict | None) -> str:
    """Pull the most identifying field from a SapientMessage dict for display."""
    if not isinstance(msg, dict):
        return ""
    for top in ("registration", "registration_ack", "status_report",
                "detection_report", "task", "task_ack",
                "alert", "alert_ack", "error"):
        sub = msg.get(top)
        if not isinstance(sub, dict):
            continue
        for key in ("alert_id", "task_id", "report_id", "object_id",
                    "icd_version", "alert_ack_status", "task_status",
                    "acceptance"):
            if key in sub:
                v = sub[key]
                if isinstance(v, (list, dict)):
                    continue
                short = str(v)
                if len(short) > 28:
                    short = short[:25] + "..."
                return f"{key}={short}"
    return ""


@app.get("/api/runs")
def api_list_runs() -> list[dict]:
    runs_dir = Path("/app/runs")
    out: list[dict] = []
    if not runs_dir.exists():
        return out
    for d in sorted(runs_dir.iterdir(), reverse=True)[:50]:
        f = d / "result.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text())
            transcript = data.get("transcript", [])
            sent = next((t for t in transcript if t["direction"] == "sent"), None)
            recvs = [t for t in transcript if t["direction"] == "recv"]
            out.append({
                "run_id": data.get("run_id", d.name),
                "host": data.get("host"),
                "port": data.get("port"),
                "template": data.get("template"),
                "started_utc": data.get("started_utc"),
                "error": data.get("error"),
                "n_received": len(recvs),
                "sent_content": (sent or {}).get("content"),
                "sent_summary": _summarise_message((sent or {}).get("message")),
                "recv_contents": [r.get("content") for r in recvs],
                "recv_summaries": [_summarise_message(r.get("message")) for r in recvs],
            })
        except Exception as exc:
            out.append({"run_id": d.name, "error": f"parse: {exc}"})
    return out


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: str) -> dict:
    f = Path("/app/runs") / run_id / "result.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return json.loads(f.read_text())


@app.delete("/api/runs")
def api_clear_runs() -> dict:
    """Delete every per-run directory under /app/runs. Destructive — the
    JSON transcripts are the only record once removed, but they're easy
    to regenerate by re-running the flow."""
    import shutil
    runs_dir = Path("/app/runs")
    removed: list[str] = []
    if runs_dir.exists():
        for d in runs_dir.iterdir():
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                    removed.append(d.name)
                except OSError as exc:
                    log.warning("could not remove %s: %s", d, exc)
    return {"removed": removed, "count": len(removed)}


# --- NTP --------------------------------------------------------------------

@app.get("/api/ntp")
async def api_ntp(server: str | None = None, timeout: float = 2.0) -> dict:
    srv = server or os.environ.get("MSF_NTP_SERVER", ntp.DEFAULT_SERVER)
    result = await ntp.query(server=srv, timeout=timeout)
    return result.to_dict()


# --- Nodes (and its filtered views) -----------------------------------------

@app.get("/api/nodes")
async def api_nodes(type: str | None = None) -> dict:
    """Unified registry + status for every named platform resource. Proxy
    through to the `nodes` service. `?type=…` filters to a subset
    (platform-node, middleware, …) — the UI's two drawers use that to
    render one source of truth two ways."""
    return await nodes.fetch_current(type=type)


# Back-compat shim for the old UI URL. Filtered view of /api/nodes —
# returns the same payload shape under "middlewares" so any consumer
# still calling /api/middlewares keeps working through the migration.
@app.get("/api/middlewares")
async def api_middlewares() -> dict:
    payload = await nodes.fetch_current(type="middleware")
    return {"config_error": payload.get("config_error"),
            "interval_s": payload.get("interval_s"),
            "middlewares": payload.get("nodes", [])}


class NodePatch(BaseModel):
    # Same field set as the nodes service expects — id/type immutable.
    name: str | None = Field(None, min_length=1, max_length=128)
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


class NodeCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    host: str = Field(..., min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


def _proxy_error(exc: Exception) -> HTTPException:
    """Map urllib HTTPErrors back to the right status + detail. Anything
    else becomes a 502 (the nodes service errored, we're a proxy)."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8")
            detail = json.loads(body).get("detail", body) if body else exc.reason
        except Exception:
            detail = str(exc)
        return HTTPException(status_code=exc.code, detail=detail)
    return HTTPException(status_code=502, detail=f"nodes service: {exc}")


@app.post("/api/nodes", status_code=201)
async def api_create_node(req: NodeCreate) -> dict:
    body = req.model_dump(exclude_none=True)
    try:
        return await nodes.create(body)
    except Exception as exc:
        raise _proxy_error(exc)


@app.patch("/api/nodes/{node_id}")
async def api_patch_node(node_id: str, req: NodePatch) -> dict:
    body = req.model_dump(exclude_none=True)
    if not body:
        raise HTTPException(status_code=400,
                            detail="provide at least one field to update")
    try:
        return await nodes.patch_one(node_id, body)
    except Exception as exc:
        raise _proxy_error(exc)


@app.delete("/api/nodes/{node_id}")
async def api_delete_node(node_id: str) -> dict:
    try:
        return await nodes.delete(node_id)
    except Exception as exc:
        raise _proxy_error(exc)


# Back-compat shim for the old PATCH URL — routed through the unified
# /api/nodes PATCH. Same payload subset (host/port/probe). Kept so any
# old browser session or scripted caller using /api/middlewares still
# works. Will be removed after a deprecation window.
@app.patch("/api/middlewares/{mw_id}")
async def api_patch_middleware(mw_id: str, req: NodePatch) -> dict:
    return await api_patch_node(mw_id, req)


# --- GPS --------------------------------------------------------------------

@app.get("/api/gps")
def api_gps() -> dict:
    """Return the latest fix from the NMEA-over-UDP listener."""
    return gps.current_fix().to_dict()


@app.get("/api/gps/raw")
def api_gps_raw() -> dict:
    """Return listener stats + the last few raw datagrams (hex + ascii) so
    operators can see what the router is actually pushing — including any
    prefix the gateway prepends before the NMEA `$`."""
    if gps.listener is None:
        return {"error": "listener not running"}
    return gps.listener.stats()


# --- Clocks (NTP + local + Windows-via-SAPIENT-ack) ------------------------

@app.get("/api/clocks")
async def api_clocks(
    ntp_server: str | None = None,
    ntp_timeout: float = 2.0,
    windows_host: str | None = None,
    windows_port: int = 14000,
    windows_node_id: str = "00000000-0000-4000-8000-000000000001",
    include_windows: bool = False,
) -> dict:
    """Composite clock view: local container/host clock, NTP server clock,
    and (if `include_windows=true`) the Windows harness clock extracted from
    a SAPIENT RegistrationAck timestamp.
    """
    local = clocks.local_clock()
    ntp_sample = await clocks.ntp_clock(server=ntp_server, timeout=ntp_timeout)
    win = None
    if include_windows and windows_host:
        win = await clocks.windows_clock_via_sapient(
            host=windows_host, port=windows_port, node_id=windows_node_id
        )
    gps_fix = gps.current_fix()
    return {
        "local": local.to_dict(),
        "ntp": ntp_sample.to_dict(),
        "windows": win.to_dict() if win is not None else None,
        "gps": gps_fix.to_dict(),
        "deltas": clocks.deltas_summary(local, ntp_sample, win),
    }
