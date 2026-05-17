"""Run a templated SapientMessage against a configured endpoint and capture
the wire conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

from sapient_wire import framer
from .templates_loader import message_to_dict

log = logging.getLogger(__name__)

RUNS_DIR = Path("/app/runs")


class RunResult(dict):
    pass


async def send_one(
    *,
    host: str,
    port: int,
    payload: bytes,
    template_name: str,
    decoded_sent: dict,
    recv_timeout_s: float = 5.0,
    drain_after_s: float = 1.0,
    connect_timeout_s: float = 5.0,
) -> RunResult:
    """Open TCP, send one length-prefixed payload, drain responses for a window.

    Returns a transcript dict; also writes the run to disk under RUNS_DIR.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:6]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    transcript: list[dict] = []
    t0 = time.monotonic()

    def stamp(direction: str, raw: bytes, decoded: dict) -> None:
        transcript.append({
            "t_ms": round((time.monotonic() - t0) * 1000.0, 3),
            "direction": direction,
            "bytes": len(raw),
            "content": decoded.get("content"),
            "message": decoded.get("message"),
        })

    error: str | None = None

    if not host:
        error = "connect failed: host is empty (set Host in the top bar)"
        return _finalise(run_dir, run_id, host, port, template_name,
                         transcript, decoded_sent, error)

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=connect_timeout_s
        )
    except socket.gaierror as exc:
        error = f"connect failed: cannot resolve host {host!r}: {exc}"
        return _finalise(run_dir, run_id, host, port, template_name,
                         transcript, decoded_sent, error)
    except asyncio.TimeoutError:
        error = f"connect failed: timeout after {connect_timeout_s}s to {host}:{port}"
        return _finalise(run_dir, run_id, host, port, template_name,
                         transcript, decoded_sent, error)
    except OSError as exc:
        error = f"connect failed to {host}:{port}: {exc}"
        return _finalise(run_dir, run_id, host, port, template_name,
                         transcript, decoded_sent, error)

    try:
        # Send.
        writer.write(framer.encode(payload))
        await writer.drain()
        stamp("sent", payload, {"content": decoded_sent.get("_content"),
                                "message": decoded_sent})

        # Drain inbound.
        deadline = asyncio.get_event_loop().time() + recv_timeout_s + drain_after_s
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                header = await asyncio.wait_for(
                    reader.readexactly(framer.HEADER_LEN), timeout=remaining
                )
            except asyncio.TimeoutError:
                break
            except asyncio.IncompleteReadError:
                break
            (length,) = framer._HEADER.unpack(header)
            try:
                body = await asyncio.wait_for(
                    reader.readexactly(length),
                    timeout=max(0.1, deadline - asyncio.get_event_loop().time()),
                )
            except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
                error = f"truncated reply: {exc}"
                break
            inbound = _msg.SapientMessage()
            try:
                inbound.ParseFromString(body)
                inbound_dict = message_to_dict(inbound)
                content = inbound.WhichOneof("content")
            except Exception as exc:
                inbound_dict = {"_parse_error": str(exc)}
                content = None
            stamp("recv", body, {"content": content, "message": inbound_dict})

    except Exception as exc:
        error = f"runtime error: {exc}"
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    return _finalise(run_dir, run_id, host, port, template_name,
                     transcript, decoded_sent, error)


def _finalise(run_dir: Path, run_id: str, host: str, port: int,
              template_name: str, transcript: list[dict],
              decoded_sent: dict, error: str | None) -> RunResult:
    result = RunResult({
        "run_id": run_id,
        "host": host,
        "port": port,
        "template": template_name,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "sent_message": decoded_sent,
        "transcript": transcript,
    })
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    return result
