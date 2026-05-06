# Scenario: task

## Spec reference
BSI Flex 335 v2.0 §4.7, Table 78 Task message fields, Table 86 Task
acknowledgement fields.

## Harness configuration

Same as [`detection`](detection.md). `SapientDmmSimulator` is configured to
issue a Task once it sees a registration.

## Driver actions (Ubuntu)

`drive_scenario.py task`:

1. Run registration + status fixture.
2. Wait up to 10 s for an inbound `SapientMessage` with `content = Task`
   addressed to the driver's `node_id` (`destination_id` set).
3. Send back one `SapientMessage` with `content = TaskAck`:
   - `task_id` = the value from the inbound Task.
   - `task_status = TASK_STATUS_ACCEPTED`.
4. Close.

## Expected at the harness

Reference DB has one Task row and one TaskAck row tied by `task_id`. The
TaskAck is forwarded up to the HLDMM tasking link.

## Replay pass criteria

- Inbound Task forwarded to the driver byte-equal to the reference.
- Outbound TaskAck forwarded by the new middleware to the fusion-facing
  port byte-equal to the driver's emitted bytes.
- New schema `task` and `task_ack` tables each have one row, both linked
  by the same `task_id`.
