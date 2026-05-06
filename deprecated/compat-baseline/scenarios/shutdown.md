# Scenario: shutdown

## Spec reference
BSI Flex 335 v2.0 §4.8 Node shutdown.

## Harness configuration

Same as [`status`](status.md).

## Driver actions (Ubuntu)

`drive_scenario.py shutdown`:

1. Run registration + one StatusReport.
2. Send `SapientMessage{content=StatusReport, system=SYSTEM_GOODBYE}`.
3. Close the TCP connection.

## Expected at the harness

The reference logs the GOODBYE and removes the `node_id` from its in-memory
registry; one final StatusReport row is written to PostgreSQL with
`system=GOODBYE`.

## Replay pass criteria

- Forwarded GOODBYE StatusReport is byte-equal to the reference.
- New schema `status_report` table has a row with `system='GOODBYE'`.
- A subsequent connection from the same `node_id` is treated as a fresh
  registration (the registry no longer has a TTL-grace entry, even within
  2 min, because §4.8 GOODBYE is an explicit teardown).
