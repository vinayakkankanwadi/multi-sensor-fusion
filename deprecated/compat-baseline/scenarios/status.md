# Scenario: status

## Spec reference
BSI Flex 335 v2.0 §4.5 b, Table 60 StatusReport fields, Table 24 status report
fields in the registration.

## Harness configuration

Same as [`registration`](registration.md). The driver completes registration
first.

## Driver actions (Ubuntu)

`drive_scenario.py status`:

1. Run the registration sub-sequence (same as the `registration` scenario,
   reused as a fixture).
2. Send three `SapientMessage` with `content = StatusReport`, spaced at the
   `status_interval` declared in the registration (5 s).
   - `report_id` = monotonically increasing ULID.
   - `system = SYSTEM_OK` for the first two.
   - `system = SYSTEM_WARNING` with one populated `info` field for the third,
     to exercise the on-change path.
3. Close the TCP connection after the third report is sent.

## Expected at the harness

PostgreSQL `status_report_*` tables gain three rows with the matching
`report_id`s. Forwarded StatusReports appear on the HLDMM tasking link.

## Replay pass criteria

- Three forwarded StatusReports byte-equal to the reference (no field
  mutation by the new middleware).
- Three rows in the new schema's `status_report` table; `report_id` ULIDs
  match the reference; `system` enum values match.
- Latency columns (`comms_latency_ms`, `db_latency_ms`) are not compared
  for byte equality — they are environment-dependent.
