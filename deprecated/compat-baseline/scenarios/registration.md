# Scenario: registration

## Spec reference
BSI Flex 335 v2.0 §4.4 Initialization, Table 15 Registration message structure,
Table 16 RegistrationAck.

## Harness configuration

Windows host running:
- `SapientDataAgent` in DMM mode (listens on `:14000` for SDAs and on `:12002`
  for HLDMM-side tasking).
- `SapientDataAgent` in SDA mode (listens on `:14000` for ASMs; this scenario
  may bypass it and connect the driver directly to the DMM-DA).
- `SapientDmmSimulator` connected to the DMM-DA tasking port — this is what
  generates the RegistrationAck.

`app.config`: `ClientAddress=0.0.0.0` so the listener is reachable from the
Ubuntu LAN.

## Driver actions (Ubuntu)

`drive_scenario.py registration`:

1. Open TCP to `$SAPIENT_HOST:$SAPIENT_DA_PORT`.
2. Send one `SapientMessage` with `content = Registration`:
   - `timestamp` = now (UTC)
   - `node_id` = a fixed test UUID (committed alongside the scenario)
   - `Registration.node_definition[0].node_type = NODE_TYPE_RADAR`
   - `Registration.icd_version = "BSI_Flex_335_v2.0"`
   - one `Registration.capabilities` entry, one `Registration.config_data`,
     one `Registration.status_definition` with a 5s `status_interval`,
     one `Registration.mode_definition` with the minimum mandatory fields.
3. Wait up to 10s for one inbound `SapientMessage` with
   `content = RegistrationAck`.
4. Close the TCP connection.

## Expected at the harness

PostgreSQL `sensor_registration_BSIFlex335v2` gains one row with the
driver's `node_id`. Logs show "Sensor Registration Message Received" and
the forward to the HLDMM tasking link.

## Replay pass criteria

Against the new Python middleware on Ubuntu:

- Outbound forwarded `Registration` to the fusion-facing port is byte-equal
  to the captured Windows-forwarded bytes (the new middleware is transparent
  — no `node_id` or other field rewrite).
- New schema `registration` table gains exactly one row with the same
  `node_id`, `icd_version`, and timestamp as the reference.
- New schema does not gain rows in `sensor_location_offset` (correctly
  absent) or `objective` / `route_plan` (Zodiac tables — absent in the new
  schema).
- RegistrationAck produced by the upstream fusion (or its mock) is
  forwarded back to the driver byte-equal to the reference.
