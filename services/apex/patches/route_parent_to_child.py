"""Local patch over vendored Apex (dstl/Apex-SAPIENT-Middleware).

Two fixes to ParentConnection.handle_message, both diagnosed by reading
BSI's ASM_DA1 logs from the deployed Windows box:

1) **Route downstream-bound messages by destination_node_id** so acks
   (registration_ack, task_ack, alert_ack) coming back from an upstream
   Parent reach the originating Child. Same lookup that DMMConnection
   already does — without it, BSI's real RegistrationAck would never
   reach UI.

2) **Fix the except_writer comparison** so a message returning on one
   Parent connection doesn't get reflected back to that same Parent.
   send_to_parent's loop iterates `parent_all_writers` (List[ParentWriter])
   and compares each entry to `except_writer`. Upstream Apex passes
   `self.writer` (a WriterType **function**) for except_writer — but the
   list holds ParentWriter **dataclasses**, so the inequality check is
   always True and the message gets reflected. Pass `self.parent_writer`
   (the actual ParentWriter object that gets appended to
   `parent_all_writers`) so the skip works.

The combination of these two bugs in upstream Apex was the source of
BSI's `Unknown Middleware Response: RegistrationACK` warnings — BSI's
real ack came back through Apex, never reached UI, AND was reflected
right back at BSI's ASM_DA1, whose SapientDataAgentClientProtocol has
no case for an ack on its inbound (client-from-ASM) side.

Run at image build time; in-place edit on
/app/sapient_apex_server/connection.py. Idempotent — re-running on a
patched file is a no-op (and exits 0).
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path("/app/sapient_apex_server/connection.py")

BEFORE = """\
    def handle_message(self, msg: MessageRecord, generator: IdGenerator):
        msg.updated_data_bytes = msg.received.data_bytes
        if msg.error is None:
            for writer in self.shared_data.dmm_writers:
                writer(msg, msg.sapient_version)
            msg.forwarded_count = len(self.shared_data.dmm_writers)

            self.shared_data.send_to_parent(msg, high_level=False, except_writer=self.writer)
"""

AFTER = """\
    def handle_message(self, msg: MessageRecord, generator: IdGenerator):
        msg.updated_data_bytes = msg.received.data_bytes
        if msg.error is None:
            msg.forwarded_count = 0

            # PATCH (services/apex/patches/route_parent_to_child.py):
            # route to specific child by destination_node_id so downstream
            # acks (registration_ack, task_ack, alert_ack) from an upstream
            # Parent reach the originating Child. Mirrors the
            # destination_node_id lookup already in DMMConnection.handle_message.
            dest_id = msg.parsed.destination_node_id
            if dest_id is not None and dest_id in self.shared_data.registered_sensors:
                node_connection = self.shared_data.registered_sensors[dest_id]
                node_connection.writer(msg, msg.sapient_version)
                msg.forwarded_count += 1

            for writer in self.shared_data.dmm_writers:
                writer(msg, msg.sapient_version)
            msg.forwarded_count += len(self.shared_data.dmm_writers)

            # PATCH: pass self.parent_writer (the ParentWriter object
            # in parent_all_writers) — not self.writer (a WriterType
            # function) — so send_to_parent's "skip the sender" check
            # actually matches and the message isn't reflected back.
            self.shared_data.send_to_parent(msg, high_level=False, except_writer=self.parent_writer)
"""

MARKER = "PATCH (services/apex/patches/route_parent_to_child.py)"


def main() -> int:
    text = TARGET.read_text()
    if MARKER in text:
        print(f"{TARGET}: already patched, skipping")
        return 0
    if BEFORE not in text:
        print(f"{TARGET}: BEFORE block not found — Apex upstream may have changed; "
              f"re-derive this patch against the current source.", file=sys.stderr)
        return 1
    TARGET.write_text(text.replace(BEFORE, AFTER, 1))
    print(f"{TARGET}: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
