# deprecated/

Code that has been **superseded** by newer work in the repo. Kept for
history (or because the captured artifacts are still useful), not for
active use. Nothing in here should be imported by any live component.

## What's in here

### `compat-baseline/`

The original CLI harness for capturing wire-level baselines from the
Windows BSI Flex 335 v2 Test Harness. Built before the UI existed;
everything it did is now done by the Docker UI under [`../ui/`](../ui/).

| Sub-folder | What it was | Replaced by |
|---|---|---|
| `edge-sim/` | Python CLI driver: framer, recorder, builders, scenarios | `ui/app/` (framer.py, runner.py, templates_loader.py) + `ui/templates/` |
| `replay/` | Stub placeholders for "replay captured baselines against new middleware" — never implemented | The UI just changes its Host/Port at runtime to talk to either the Windows reference or the future Python middleware |
| `scenarios/*.md` | Markdown specs of each scenario | live JSON templates + flow composer in the UI |
| `baselines/` | 15 captured wire baselines from the Windows harness during early debugging | n/a (trivially reproducible by running flows in the UI) |

The validator quirks discovered while building this — `icd_version`
literal, `StatusReport.mode`, `TaskDefinition.concurrent_tasks`,
`Duration.value` non-zero — are encoded in
[`../ui/app/proto_to_template.py`](../ui/app/proto_to_template.py)
`_VALIDATOR_QUIRKS`, so nothing was lost in the move.

### `tak-server-cot/`

Standalone Python CLI for sending Cursor-on-Target XML over UDP to a TAK
Server. Built first, to prove the TAK ingest path worked. Superseded by
the standalone [`../cot-bridge/`](../cot-bridge/) service: SAPIENT TCP in
(length-prefix protobuf), CoT XML out (UDP). Apex's outbound Parent
forwardAll connection points at it on 5005.

### `sapient/`

Happy-path Linux SAPIENT stub that answered `Registration` with a synthetic
`RegistrationAck`. Useful for offline mock-ups before Apex was vendored.
Apex now covers every flow the stub did (and every flow the .NET reference
does), so the stub is no longer in the compose file. The Dockerfile and
sources stay here in case we ever want a deterministic offline target.

### `ui-tak/`

The UI's own SAPIENT → CoT → TAK fan-out (`tak_bridge.py`) and TAK-echo
listener (`tak_echo.py`). When Apex got plumbed in front of the UI, TAK
fan-out moved to the middleware: Apex Parent forwardAll → `cot-bridge` →
TAK over UDP. Having the UI also fan out was duplicate work and made
"which path sent that CoT?" harder to answer, so the UI's TAK code was
retired here. Restore from history if you ever want an edge to bypass
the middleware (e.g. middleware down, direct-to-TAK probe).

### `nodes-legacy/` and `middlewares-legacy/`

The original split into two services: `msf-nodes` (platform-host registry
aggregating NTP + GPS into one severity per node) and `msf-middlewares`
(SAPIENT-endpoint registry with TCP probing + editable host/port via
PATCH). They worked, but ~90 % of the code was identical scaffolding —
config loader, periodic prober, status cache, HTTP read/PATCH API — with
the only real difference being the probe strategy. Adding a third type
(TAK server, edge node, fusion node, …) would have meant a third copy of
the same boilerplate.

Both retired into one container — [`../nodes/`](../nodes/) — keyed on a
`type` field per config entry and dispatching to per-type probe modules
under `app/probes/`. Same data shapes for the UI; same `/nodes/current`,
`/nodes/{id}`, `PATCH /nodes/{id}` endpoints (the old `/middlewares/*`
URLs continue to work as filtered back-compat shims through the UI).

Drop these two folders once the unified `nodes/` service has had a few
weeks of comfortable use and nobody has needed to flip back.

## When to delete this folder

Once we have a few weeks of comfortable use of the new stack and nothing
in here has been needed, delete the whole `deprecated/` folder. Until
then, history is cheap; deletion is permanent.
