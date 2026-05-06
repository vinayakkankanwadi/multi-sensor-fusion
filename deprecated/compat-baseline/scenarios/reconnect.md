# Scenario: reconnect

## Spec reference
BSI Flex 335 v2.0 §4.9 Lost connection.

## Harness configuration

Same as [`status`](status.md). The reference's `AsmReconnectionTimeout`
default applies.

## Driver actions (Ubuntu)

`drive_scenario.py reconnect`:

1. Run registration + one StatusReport.
2. Close the TCP connection abruptly (SO_LINGER 0).
3. Wait 30 s.
4. Reconnect to the same port.
5. Send one StatusReport without re-registering.
6. Confirm: the harness still routes the StatusReport (the registry remembered
   the `node_id` because reconnect was within 2 min).
7. Close.
8. Wait 130 s (longer than 2 min).
9. Reconnect.
10. Send a StatusReport without re-registering.
11. Confirm: the harness rejects (the registry has expired the `node_id`).
12. Send a Registration.
13. Confirm: the harness accepts.
14. Close.

## Expected at the harness

Two StatusReport rows from the within-2-min phase, plus one new Registration
row from the post-2-min phase. No StatusReport row is created during the
post-2-min phase before re-registration.

## Replay pass criteria

- Reconnect-within-2-min: the new middleware's behavior matches the reference
  (StatusReport accepted, no new Registration row).
- Reconnect-after-2-min: the new middleware also rejects the StatusReport
  until a Registration is received.
- Registry TTL is parameterised in middleware config and defaults to 2 min
  per spec.
