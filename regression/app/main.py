"""FastAPI entrypoint for the regression UI.

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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import clocks, flow, gps, ntp, proto_to_template, runner, tak_bridge, tak_echo, templates_loader, validators

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await gps.start_listener()
    await tak_echo.start_listener()
    log.info("startup complete")
    try:
        yield
    finally:
        await gps.stop_listener()
        await tak_echo.stop_listener()


app = FastAPI(title="msf-regression-ui",
              version="3",
              description="Send any SAPIENT BSI Flex 335 v2 templated message to a configurable endpoint.",
              lifespan=_lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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
    also_send_to_tak: bool = Field(False,
        description="If true, also convert to CoT and send to the configured TAK Server")
    tak_host: str | None = Field(None, description="Override MSF_TAK_HOST")
    tak_port: int | None = Field(None, description="Override MSF_TAK_PORT")
    await_tak_echo: bool = Field(False,
        description="If true and also_send_to_tak is true, wait for our CoT to be echoed back from TAK")
    tak_echo_timeout_s: float = Field(4.0, ge=0.0, le=30.0)


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

    if req.also_send_to_tak:
        if req.await_tak_echo:
            tak_res = await tak_bridge.fan_out_with_echo(
                message, host=req.tak_host, port=req.tak_port,
                echo_timeout_s=req.tak_echo_timeout_s)
        else:
            tak_res = tak_bridge.fan_out(message,
                                         host=req.tak_host, port=req.tak_port)
        result["tak"] = tak_res.to_dict()

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
    also_send_to_tak: bool = False
    tak_host: str | None = None
    tak_port: int | None = None
    await_tak_echo: bool = False
    tak_echo_timeout_s: float = 4.0


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
    on_sent = None
    if req.also_send_to_tak:
        if req.await_tak_echo:
            async def _on_sent(message):
                r = await tak_bridge.fan_out_with_echo(
                    message, host=req.tak_host, port=req.tak_port,
                    echo_timeout_s=req.tak_echo_timeout_s)
                return r.to_dict()
        else:
            def _on_sent(message):
                return tak_bridge.fan_out(message,
                                           host=req.tak_host, port=req.tak_port).to_dict()
        on_sent = _on_sent
    try:
        return await flow.run_flow(
            host=req.host.strip(), port=req.port, node_id=req.node_id,
            steps=steps, validate_before_send=req.validate_before_send,
            on_sent=on_sent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- Runs -------------------------------------------------------------------

def _summarise_tak(steps: list[dict] | None, top_tak: dict | None) -> str:
    """Compact one-line TAK summary for /api/runs row."""
    if top_tak:
        if top_tak.get("sent"):
            return f"TAK: sent {top_tak.get('bytes_sent')}B {top_tak.get('cot_type', '')}"
        if top_tak.get("error"):
            return f"TAK: ERR {top_tak['error']}"
        if top_tak.get("skipped_reason"):
            return f"TAK: skip ({top_tak['skipped_reason']})"
        return ""
    if not steps:
        return ""
    sent = sum(1 for s in steps if (s.get("tak") or {}).get("sent"))
    skipped = sum(1 for s in steps if (s.get("tak") or {}).get("skipped_reason"))
    err = sum(1 for s in steps if (s.get("tak") or {}).get("error"))
    if sent + skipped + err == 0:
        return ""
    parts = []
    if sent:    parts.append(f"{sent}✓")
    if skipped: parts.append(f"{skipped}skip")
    if err:     parts.append(f"{err}err")
    return f"TAK: {' '.join(parts)}"


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
                "tak_summary": _summarise_tak(data.get("steps"), data.get("tak")),
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


# --- NTP --------------------------------------------------------------------

@app.get("/api/ntp")
async def api_ntp(server: str | None = None, timeout: float = 2.0) -> dict:
    srv = server or os.environ.get("MSF_NTP_SERVER", ntp.DEFAULT_SERVER)
    result = await ntp.query(server=srv, timeout=timeout)
    return result.to_dict()


# --- GPS --------------------------------------------------------------------

@app.get("/api/gps")
def api_gps() -> dict:
    """Return the latest fix from the NMEA-over-UDP listener."""
    return gps.current_fix().to_dict()


@app.get("/api/tak/echo")
def api_tak_echo() -> dict:
    """Return TAK echo listener stats + last 20 received CoT UIDs."""
    if tak_echo.listener is None:
        return {"error": "echo listener not running"}
    return tak_echo.listener.stats()


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
