"""Diagnostic patch: log every write that exits send_to_parent.

Three post-patch "Unknown Middleware Response:RegistrationACK" entries
still appear in BSI's USB log at 15:45:04, 15:46:45, 15:54:37 BSI-local
on 2026-05-18 — after the route_parent_to_child patch landed.
We've ruled out the Peer-port culprit (nothing connects to :5001).
The remaining suspects are the three other send_to_parent call sites
(ChildConnection line 383, PeerConnection line 508, RecorderConnection
line 628) — none of which pass `except_writer`.

This patch wraps the inner loop of SharedData.send_to_parent so every
parent-bound write logs:
  - message_type / node_id / destination_node_id
  - payload byte length (so we can correlate against BSI's 59/60-byte
    Server Receive Thread events)
  - id() of writer and except_writer (proves the equality check)
  - 6-frame Python stack (identifies WHICH send_to_parent call site
    fired)

Idempotent. Re-running on a patched file is a no-op.
Remove after the reflection source is identified.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("/app/sapient_apex_server/connection.py")

BEFORE = """\
        for writer in writers:
            if writer != except_writer:
                writer.writer(msg, msg.sapient_version)
                msg.forwarded_count += 1
"""

AFTER = """\
        for writer in writers:
            if writer != except_writer:
                # DIAG (services/apex/patches/diag_send_to_parent.py)
                import logging as _diag_logging
                import traceback as _diag_tb
                _diag_logging.getLogger("apex").warning(
                    "DIAG send_to_parent: type=%s node=%s dest=%s bytes=%d "
                    "writer_id=%s except_id=%s\\n%s",
                    getattr(msg.parsed, "message_type", None),
                    getattr(msg.parsed, "node_id", None),
                    getattr(msg.parsed, "destination_node_id", None),
                    len(msg.updated_data_bytes or b""),
                    id(writer),
                    id(except_writer),
                    "".join(_diag_tb.format_stack(limit=8)),
                )
                writer.writer(msg, msg.sapient_version)
                msg.forwarded_count += 1
"""

MARKER = "DIAG (services/apex/patches/diag_send_to_parent.py)"


def main() -> int:
    text = TARGET.read_text()
    if MARKER in text:
        print(f"{TARGET}: already diag-patched, skipping")
        return 0
    if BEFORE not in text:
        print(
            f"{TARGET}: BEFORE block not found — Apex upstream may have changed; "
            f"re-derive this patch against the current source.",
            file=sys.stderr,
        )
        return 1
    TARGET.write_text(text.replace(BEFORE, AFTER, 1))
    print(f"{TARGET}: diag-patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
