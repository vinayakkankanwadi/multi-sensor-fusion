"""Captures wire bytes (both directions) and decoded SapientMessages to a
baseline directory.

Layout written:
    <baseline_dir>/
        sent.bin            length-prefixed wire bytes the driver sent
        recv.bin            length-prefixed wire bytes the driver received
        transcript.jsonl    one JSON object per message, both directions, in order
        manifest.json       scenario, host, port, ulid, start/end UTC, git SHA
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.protobuf import json_format

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

from . import framer


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_sha(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


class Recorder:
    """Per-scenario recorder. One instance per scenario run."""

    def __init__(self, baselines_dir: Path, scenario: str, host: str, port: int) -> None:
        self.scenario = scenario
        self.host = host
        self.port = port
        self.dir = baselines_dir / scenario / utc_stamp()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._sent = (self.dir / "sent.bin").open("wb")
        self._recv = (self.dir / "recv.bin").open("wb")
        self._tx = (self.dir / "transcript.jsonl").open("w")
        self._t0 = time.monotonic()
        self._start_utc = datetime.now(timezone.utc).isoformat()
        self._end_utc: str | None = None

    def _log(self, direction: str, payload: bytes) -> None:
        msg = _msg.SapientMessage()
        try:
            msg.ParseFromString(payload)
            decoded: Any = json_format.MessageToDict(
                msg, preserving_proto_field_name=True
            )
            content = msg.WhichOneof("content")
        except Exception as exc:
            decoded = {"_parse_error": str(exc)}
            content = None
        record = {
            "t_ms": round((time.monotonic() - self._t0) * 1000.0, 3),
            "direction": direction,
            "bytes": len(payload),
            "content": content,
            "message": decoded,
        }
        self._tx.write(json.dumps(record) + "\n")
        self._tx.flush()

    def record_sent(self, payload: bytes) -> None:
        self._sent.write(framer.encode(payload))
        self._sent.flush()
        self._log("sent", payload)

    def record_recv(self, payload: bytes) -> None:
        self._recv.write(framer.encode(payload))
        self._recv.flush()
        self._log("recv", payload)

    def close(self, status: str = "ok", note: str | None = None) -> None:
        self._end_utc = datetime.now(timezone.utc).isoformat()
        self._sent.close()
        self._recv.close()
        self._tx.close()
        manifest = {
            "scenario": self.scenario,
            "host": self.host,
            "port": self.port,
            "start_utc": self._start_utc,
            "end_utc": self._end_utc,
            "status": status,
            "note": note,
            "git_sha": _git_sha(self.dir.resolve().parents[3]),
        }
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.close("ok")
        else:
            self.close("error", note=f"{exc_type.__name__}: {exc}")
