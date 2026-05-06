# Scenario: alert

## Spec reference
BSI Flex 335 v2.0 §4.6, Table 88 Alert message, Table 93 AlertAck.

## Harness configuration

Same as [`task`](task.md). `SapientDmmSimulator` is configured to issue an
AlertAck (one accept, one reject) in response to inbound Alerts.

## Driver actions (Ubuntu)

`drive_scenario.py alert`:

1. Run registration + status fixture.
2. Send `SapientMessage{content=Alert, priority=PRIORITY_HIGH}`. Wait for an
   `AlertAck` with `status = ALERT_ACK_STATUS_ACCEPT`.
3. Send `SapientMessage{content=Alert, priority=PRIORITY_LOW}`. Wait for an
   `AlertAck` with `status = ALERT_ACK_STATUS_REJECT` and a populated
   `reason`.
4. Close.

## Expected at the harness

Reference DB: two Alert rows, **zero AlertAck rows** (the reference does not
persist AlertAck — known issue per its README).

## Replay pass criteria

- Two forwarded Alerts byte-equal to the reference.
- Two AlertAcks forwarded back to the driver byte-equal to the reference.
- New schema `alert` table: two rows.
- New schema `alert_ack` table: **two rows** — this is an *expected delta*
  from the reference. The new middleware deliberately persists AlertAck
  per spec §4.6, fixing the reference's known omission.
