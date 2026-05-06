# Scenario: detection

## Spec reference
BSI Flex 335 v2.0 §4.5 c, Table 69 DetectionReport fields.

## Harness configuration

Same as [`status`](status.md).

## Driver actions (Ubuntu)

`drive_scenario.py detection`:

1. Run the registration + first-StatusReport sub-sequence as a fixture.
2. Send three `SapientMessage` with `content = DetectionReport`:
   - first uses `location` (Cartesian),
   - second uses `range_bearing`,
   - third uses `location` plus `velocity` and one `class[]` entry.
3. Close the TCP connection.

## Expected at the harness

The reference's `detection_report_location_*`, `detection_report_range_bearing_*`,
and `detection_report_class_*` tables gain rows. The Windows reference's
`SapientDataAgentClientProtocol` *also* applies `CartesianOffset` /
`BearingOffset` if a row exists in `sensor_location_offset` — this scenario
intentionally leaves `sensor_location_offset` empty so the reference does
not mutate the message. That keeps "byte-equal" reasonable as a pass
criterion in v1 of the baseline.

## Replay pass criteria

- Three forwarded `DetectionReport` messages byte-equal to the reference.
- Three rows in the new schema's `detection_report` table; the `payload_pb`
  blob is byte-equal to what was received off the wire (this asserts
  transparency end-to-end).
- A future scenario (`detection-with-offset`) will populate
  `sensor_location_offset` on the Windows side and assert that the new
  middleware does NOT apply the offset (documented expected delta).
