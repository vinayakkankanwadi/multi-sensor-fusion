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
Server. Built first, to prove the TAK ingest path worked. Superseded by:

| Live equivalent | Where |
|---|---|
| CoT XML builder | [`../sapient-to-cot/sapient_to_cot/converter.py`](../sapient-to-cot/sapient_to_cot/converter.py) — `_build_cot()` |
| UDP send to TAK | [`../ui/app/tak_bridge.py`](../ui/app/tak_bridge.py) — `fan_out()` |
| Manual probe | UI's "Also send to TAK" checkbox or `POST /api/send … also_send_to_tak: true` |

The CoT XML builder was duplicated between the two — `cot.py:build_cot()`
and `_build_cot()` — and the duplicate was never used by the live stack
(grep across `ui/`, `sapient/`, `sapient-to-cot/` returns zero imports of
`tak_server_cot`). Removing was painless.

## When to delete this folder

Once we have a few weeks of comfortable use of the new stack and nothing
in here has been needed, delete the whole `deprecated/` folder. Until
then, history is cheap; deletion is permanent.
