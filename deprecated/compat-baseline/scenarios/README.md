# Scenarios

Each scenario is a self-contained baseline run: a fixed sequence of SAPIENT
messages driven from Ubuntu against the Windows reference harness, captured
into `../baselines/<scenario>/<timestamp>/`, and later replayed against the
new Python middleware.

| Scenario | Spec section | Drives |
|---|---|---|
| [`registration`](registration.md) | §4.4 | Edge node registers, harness acks |
| [`status`](status.md) | §4.5 b | Register + periodic StatusReports |
| [`detection`](detection.md) | §4.5 c | Register + StatusReport + DetectionReports with location and range/bearing |
| [`task`](task.md) | §4.7 | Register + StatusReport + Task from fusion + TaskAck from edge |
| [`alert`](alert.md) | §4.6 | Alert from edge + AlertAck (accept and reject) |
| [`error`](error.md) | §6.7 | Malformed-content path produces an Error message |
| [`reconnect`](reconnect.md) | §4.9 | Drop + reconnect within 2 min (no re-register) and after 2 min (re-register required) |
| [`shutdown`](shutdown.md) | §4.8 | Edge sends Status with `system=GOODBYE` |

Add new scenarios by copying an existing `.md`, listing the message sequence,
the harness configuration, and the pass criteria for replay.

## Scenario file structure

Each scenario file uses the same template:

```markdown
# Scenario: <name>

## Spec reference
Section, table, or figure that defines this behavior.

## Harness configuration
What components are started on the Windows host, what `app.config` flags,
what ports are listening.

## Driver actions (Ubuntu)
The exact sequence of SapientMessages the driver sends, in order, with
timing notes.

## Expected at the harness
What rows should appear in PostgreSQL, what messages should be forwarded
back.

## Replay pass criteria
What `diff_packets.py` and `diff_db.py` must report for the new middleware
run to be considered equivalent. Includes any expected deltas (transparency,
alert-ack persistence, etc.).
```
