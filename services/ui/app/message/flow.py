"""Multi-step SAPIENT flow runner.

A flow is an ordered list of steps. Each step renders one template, sends it
over the *same* TCP connection as the rest of the flow, and either waits for
a specific reply content type or drains for a fixed window. The whole
conversation is captured to a single transcript file.

This solves the "can't send StatusReport without re-registering" problem you
hit doing one-shot sends — the harness only registers an ASM for the lifetime
of its TCP connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

import sapient_encode_decode_msg as framer

from . import templates, validators

log = logging.getLogger(__name__)
RUNS_DIR = Path("/app/data/runs")


@dataclass
class Step:
    template_name: str
    raw_json: str | None = None
    wait_for: str | None = None      # e.g. "registration_ack"; None = drain only
    recv_timeout_s: float = 5.0
    drain_after_s: float = 0.5
    gap_before_s: float = 0.0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_flow(*, host: str, port: int, node_id: str,
                   steps: list[Step],
                   validate_before_send: bool = False,
                   gps_override: tuple[float, float, float] | None = None,
                   connect_timeout_s: float = 5.0) -> dict:
    """Open one TCP connection; run the steps in order; return a transcript."""
    if not host:
        raise ValueError("host is required")
    if not steps:
        raise ValueError("flow must contain at least one step")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    transcript: list[dict] = []
    step_results: list[dict] = []
    start_utc = _utc_iso()
    t0 = time.monotonic()

    def stamp(direction: str, content: str | None, payload: bytes,
              decoded: dict, step_idx: int) -> None:
        transcript.append({
            "t_ms": round((time.monotonic() - t0) * 1000.0, 3),
            "step": step_idx,
            "direction": direction,
            "bytes": len(payload),
            "content": content,
            "message": decoded,
        })

    # Connect once.
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=connect_timeout_s)
    except (socket.gaierror, OSError, asyncio.TimeoutError) as exc:
        return _finalise(run_dir, run_id, host, port, node_id, steps,
                         start_utc, transcript, step_results,
                         error=f"connect: {exc}")

    # Background reader: every inbound frame goes into a queue.
    inbox: asyncio.Queue[tuple[bytes, _msg.SapientMessage]] = asyncio.Queue()

    async def drain():
        try:
            async for payload in framer.read_frames(reader):
                m = _msg.SapientMessage()
                try:
                    m.ParseFromString(payload)
                except Exception as exc:
                    log.warning("inbound parse failed: %s", exc)
                    continue
                await inbox.put((payload, m))
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass

    reader_task = asyncio.create_task(drain())

    overall_error: str | None = None

    try:
        for idx, step in enumerate(steps):
            step_start = time.monotonic()
            step_record = {
                "index": idx,
                "template": step.template_name,
                "wait_for": step.wait_for,
                "validation_errors": [],
                "sent": False,
                "recv_count": 0,
                "matched_wait_for": None,
                "error": None,
            }

            if step.gap_before_s > 0:
                await asyncio.sleep(step.gap_before_s)

            # Render.
            try:
                text = step.raw_json if step.raw_json is not None \
                    else templates.get_template(step.template_name)
                message = await templates.render(
                    text, node_id=node_id, gps_override=gps_override)
            except FileNotFoundError as exc:
                step_record["error"] = f"template not found: {exc}"
                step_results.append(step_record)
                overall_error = f"step {idx}: {step_record['error']}"
                break
            except Exception as exc:
                step_record["error"] = f"render failed: {exc}"
                step_results.append(step_record)
                overall_error = f"step {idx}: {step_record['error']}"
                break

            # Optional client-side validation.
            if validate_before_send:
                errs = validators.validate(message)
                step_record["validation_errors"] = errs
                if errs:
                    step_record["error"] = "validation failed (client-side); not sent"
                    step_results.append(step_record)
                    overall_error = f"step {idx}: validation failed"
                    break

            # Send.
            payload = message.SerializeToString()
            decoded = templates.message_to_dict(message)
            stamp("sent", message.WhichOneof("content"), payload, decoded, idx)
            try:
                writer.write(framer.encode(payload))
                await writer.drain()
            except Exception as exc:
                step_record["error"] = f"write failed: {exc}"
                step_results.append(step_record)
                overall_error = f"step {idx}: {step_record['error']}"
                break
            step_record["sent"] = True

            # Receive: wait for `wait_for`, OR drain for drain_after_s.
            deadline = time.monotonic() + step.recv_timeout_s
            matched = False
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    payload, m = await asyncio.wait_for(inbox.get(),
                                                        timeout=remaining)
                except asyncio.TimeoutError:
                    break
                content = m.WhichOneof("content")
                stamp("recv", content, payload,
                      templates.message_to_dict(m), idx)
                step_record["recv_count"] += 1
                if step.wait_for and content == step.wait_for:
                    step_record["matched_wait_for"] = content
                    matched = True
                    break

            # If no specific wait_for, drain a short additional window so
            # the next step doesn't race ahead and starve unsolicited replies.
            if not step.wait_for and step.drain_after_s > 0:
                drain_deadline = time.monotonic() + step.drain_after_s
                while True:
                    remaining = drain_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        payload, m = await asyncio.wait_for(
                            inbox.get(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    stamp("recv", m.WhichOneof("content"), payload,
                          templates.message_to_dict(m), idx)
                    step_record["recv_count"] += 1

            step_record["elapsed_ms"] = round(
                (time.monotonic() - step_start) * 1000.0, 3)
            if step.wait_for and not matched:
                step_record["error"] = f"timeout waiting for {step.wait_for}"
                step_results.append(step_record)
                overall_error = f"step {idx}: {step_record['error']}"
                break
            step_results.append(step_record)
    finally:
        reader_task.cancel()
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        try:
            await reader_task
        except Exception:
            pass

    return _finalise(run_dir, run_id, host, port, node_id, steps,
                     start_utc, transcript, step_results, error=overall_error)


def _finalise(run_dir: Path, run_id: str, host: str, port: int,
              node_id: str, steps: list[Step], start_utc: str,
              transcript: list[dict], step_results: list[dict],
              error: str | None) -> dict:
    end_utc = _utc_iso()
    template_chain = "→".join(s.template_name for s in steps)

    # Ensure every step has a stable shape, even those that were never reached
    # because an earlier step short-circuited the flow.
    def _shape(idx: int, step: Step, partial: dict) -> dict:
        base = {
            "index": idx,
            "template": step.template_name,
            "wait_for": step.wait_for,
            "recv_timeout_s": step.recv_timeout_s,
            "drain_after_s": step.drain_after_s,
            "gap_before_s": step.gap_before_s,
            "sent": False,
            "recv_count": 0,
            "matched_wait_for": None,
            "validation_errors": [],
            "elapsed_ms": 0.0,
            "error": None,
            "skipped": True,
        }
        if partial:
            base.update(partial)
            base["skipped"] = False
        return base

    full_steps = [
        _shape(i, step, step_results[i] if i < len(step_results) else {})
        for i, step in enumerate(steps)
    ]

    result = {
        "run_id": run_id,
        "kind": "flow",
        "host": host,
        "port": port,
        "node_id": node_id,
        "template": f"flow:{template_chain}",  # for /api/runs columns
        "started_utc": start_utc,
        "ended_utc": end_utc,
        "error": error,
        "steps": full_steps,
        "transcript": transcript,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result


def asdict_safe(s: Step) -> dict:
    return {
        "template": s.template_name,
        "wait_for": s.wait_for,
        "recv_timeout_s": s.recv_timeout_s,
        "drain_after_s": s.drain_after_s,
        "gap_before_s": s.gap_before_s,
    }
