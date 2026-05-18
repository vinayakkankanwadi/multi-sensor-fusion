"""Message drawer — templates, single send, multi-step flow, validate, runs."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import flow, gps, proto_to_template, runner, templates, validators

log = logging.getLogger(__name__)
router = APIRouter(tags=["message"])
RUNS_DIR = Path("/app/runs")


# ---------- Templates ----------------------------------------------------

class RegenRequest(BaseModel):
    out_dir: str | None = None


@router.get("/api/templates")
def list_templates() -> list[dict]:
    return templates.list_templates()


@router.get("/api/templates/{name}")
def get_template(name: str) -> dict:
    try:
        return {"name": name, "raw": templates.get_template(name)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/api/templates")
def clear_templates() -> dict:
    """Delete every .json under templates/. Sidebar goes empty; repopulate
    via `POST /api/templates/regenerate` or by dropping .json in."""
    out_dir = Path(templates.TEMPLATES_DIR)
    removed: list[str] = []
    if out_dir.exists():
        for p in out_dir.glob("*.json"):
            try:
                p.unlink()
                removed.append(p.name)
            except OSError as exc:
                log.warning("could not remove %s: %s", p, exc)
    return {"removed": removed, "count": len(removed)}


@router.post("/api/templates/regenerate")
def regenerate_templates(req: RegenRequest | None = None) -> dict:
    out = Path((req.out_dir if req else None) or templates.TEMPLATES_DIR)
    written = proto_to_template.regenerate_all(out)
    return {"out_dir": str(out), "written": written, "count": len(written)}


# ---------- Validate -----------------------------------------------------

class ValidateRequest(BaseModel):
    node_id: str
    template_name: str | None = None
    raw_json: str | None = None


@router.post("/api/validate")
def validate(req: ValidateRequest) -> dict:
    """Run the client-side validator against a rendered template."""
    try:
        text = (req.raw_json if req.raw_json is not None
                else templates.get_template(req.template_name))
        message = templates.render(text, node_id=req.node_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        return {"ok": False, "errors": [f"render: {exc}"]}
    errors = validators.validate(message)
    return {"ok": not errors, "errors": errors,
            "content": message.WhichOneof("content")}


# ---------- Send (single message) ---------------------------------------

class SendRequest(BaseModel):
    host: str = Field(..., min_length=1, description="Target IP or hostname")
    port: int = Field(..., ge=1, le=65535)
    node_id: str = Field(..., description="UUID node_id used for {{NODE_ID}}")
    template_name: str = Field(..., description="Template stem")
    raw_json: str | None = Field(None, description="UI-edited body override")
    recv_timeout_s: float = Field(5.0, ge=0.0, le=60.0)
    drain_after_s: float = Field(1.0, ge=0.0, le=60.0)
    validate_before_send: bool = Field(False,
        description="If true, run validator and refuse to send on failure")


@router.post("/api/send")
async def send(req: SendRequest) -> dict:
    host = (req.host or "").strip()
    if not host:
        raise HTTPException(status_code=400,
                            detail="host is required (set Host before clicking Send)")
    fix = await gps.fetch_current()
    try:
        text = (req.raw_json if req.raw_json is not None
                else templates.get_template(req.template_name))
        message = templates.render(text, node_id=req.node_id, gps_fix=fix)
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
                "run_id": None, "host": req.host, "port": req.port,
                "template": req.template_name,
                "error": "validation failed (client-side); not sent",
                "validation_errors": validation_errors,
                "transcript": [],
            }

    payload = message.SerializeToString()
    decoded = templates.message_to_dict(message)
    decoded["_content"] = message.WhichOneof("content")
    result = await runner.send_one(
        host=host, port=req.port, payload=payload,
        template_name=req.template_name, decoded_sent=decoded,
        recv_timeout_s=req.recv_timeout_s, drain_after_s=req.drain_after_s,
    )
    result["validation_errors"] = validation_errors
    return result


# ---------- Send flow (multi-step over a single TCP connection) ---------

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


@router.post("/api/send_flow")
async def send_flow(req: FlowRequest) -> dict:
    if not req.steps:
        raise HTTPException(status_code=400, detail="flow needs at least one step")
    fix = await gps.fetch_current()
    steps = [
        flow.Step(template_name=s.template_name, raw_json=s.raw_json,
                  wait_for=s.wait_for, recv_timeout_s=s.recv_timeout_s,
                  drain_after_s=s.drain_after_s, gap_before_s=s.gap_before_s)
        for s in req.steps
    ]
    try:
        return await flow.run_flow(
            host=req.host.strip(), port=req.port, node_id=req.node_id,
            steps=steps, validate_before_send=req.validate_before_send,
            gps_fix=fix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------- Runs --------------------------------------------------------

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


@router.get("/api/runs")
def list_runs() -> list[dict]:
    out: list[dict] = []
    if not RUNS_DIR.exists():
        return out
    for d in sorted(RUNS_DIR.iterdir(), reverse=True)[:50]:
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


@router.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    f = RUNS_DIR / run_id / "result.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return json.loads(f.read_text())


@router.delete("/api/runs")
def clear_runs() -> dict:
    """Delete every per-run directory under /app/runs. Destructive — the
    JSON transcripts are the only record once removed."""
    removed: list[str] = []
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                    removed.append(d.name)
                except OSError as exc:
                    log.warning("could not remove %s: %s", d, exc)
    return {"removed": removed, "count": len(removed)}
