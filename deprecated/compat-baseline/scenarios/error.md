# Scenario: error

## Spec reference
BSI Flex 335 v2.0 §6.7, Table 95 Error message.

## Harness configuration

Same as [`registration`](registration.md).

## Driver actions (Ubuntu)

`drive_scenario.py error`:

1. Open TCP to the harness.
2. Send a SapientMessage that violates a mandatory-field rule (e.g. a
   StatusReport without a prior Registration for this `node_id`, or a
   DetectionReport with no `report_id`).
3. Wait up to 5 s for an inbound `SapientMessage` with `content = Error`.
4. Close.

## Expected at the harness

Reference returns an Error with the offending packet bytes echoed in
`Error.packet`. No StatusReport or DetectionReport row is created.

## Replay pass criteria

- The new middleware's Error response has the same `Error.error_message`
  category and the same `Error.packet` bytes as the reference.
- No row is created in the `status_report` / `detection_report` tables for
  the offending message.
- An entry IS created in `error` (the new schema persists Error messages
  for audit; the reference does not — *expected delta*).
