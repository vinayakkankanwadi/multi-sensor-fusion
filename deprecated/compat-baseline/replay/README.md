# Replay (Ubuntu side)

These scripts run from Ubuntu against the new Python middleware running
locally (typically via `docker compose up middleware db`). They consume
artifacts captured under `../baselines/<scenario>/<timestamp>/` and verify
that the new middleware produces equivalent behavior to the Windows
reference.

## Inputs

- `../baselines/<scenario>/<timestamp>/capture.pcap` — packets recorded
  during the Windows-targeted capture run.
- `../baselines/<scenario>/<timestamp>/postgres.dump` — *optional* baseline
  Postgres state from the Windows harness.

## Scripts

| Script | Purpose | Status |
|---|---|---|
| `replay_pcap.py` | Re-emit captured client → harness frames against the local middleware | placeholder |
| `diff_packets.py` | Diff middleware-emitted packets vs the Windows-emitted baseline packets, ignoring transport-only differences (timestamps, ULID monotonic noise) | placeholder |
| `diff_db.py` | Diff Postgres state in the new schema vs the reference baseline | placeholder |

## Pass criteria (per scenario)

Each scenario under [`../scenarios/`](../scenarios/) defines what
"equivalent" means in detail. Common rules:

- All forwarded message bytes are identical except for fields we explicitly
  document as middleware-side noise (e.g. our middleware does not mutate
  Location, so detection bytes must be byte-identical).
- DB row counts per outer-message table match the reference within a
  scenario-specific tolerance (the reference's "Zodiac" tables are not
  expected to exist in the new schema).
- Where the reference is documented as non-compliant (CartesianOffset
  mutation, fixedAsmId rewrite, missing alert-ack persistence), the new
  middleware is allowed — and required — to differ. These deltas are
  asserted as expected differences, not failures.

## Typical workflow

```bash
# 1. Bring up the new middleware locally.
docker compose -f ../../docker-compose.yml up -d middleware db

# 2. Replay a captured baseline against it.
./replay_pcap.py ../baselines/registration/<timestamp>/capture.pcap

# 3. Verify outbound packets match.
./diff_packets.py ../baselines/registration/<timestamp>/

# 4. Verify DB state matches (if a postgres.dump was captured).
./diff_db.py ../baselines/registration/<timestamp>/
```
