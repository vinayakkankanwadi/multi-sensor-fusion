# deprecated/

Code that has been **superseded** by newer work in the repo. Kept for
history (or because the captured artifacts are still useful), not for
active use. Nothing in here should be imported by any live component.

## What's in here

### `compat-baseline/`

The original CLI harness for capturing wire-level baselines from the
Windows BSI Flex 335 v2 Test Harness. Built before the regression UI
existed; everything it did is now done by the Docker UI under
[`../regression/`](../regression/).

| Sub-folder | What it was | Replaced by |
|---|---|---|
| `edge-sim/` | Python CLI driver: framer, recorder, builders, scenarios | `regression/app/` (framer.py, runner.py, templates_loader.py) + `regression/templates/` |
| `replay/` | Stub placeholders for "replay captured baselines against new middleware" — never implemented | The regression UI just changes its Host/Port at runtime to talk to either the Windows reference or the future Python middleware |
| `scenarios/*.md` | Markdown specs of each scenario | live JSON templates + flow composer in the UI |
| `baselines/` | 15 captured wire baselines from the Windows harness during early debugging | n/a (trivially reproducible by running flows in the UI) |

The validator quirks discovered while building this — `icd_version`
literal, `StatusReport.mode`, `TaskDefinition.concurrent_tasks`,
`Duration.value` non-zero — are encoded in
[`../regression/app/proto_to_template.py`](../regression/app/proto_to_template.py)
`_VALIDATOR_QUIRKS`, so nothing was lost in the move.

## When to delete this folder

Once we have a few weeks of comfortable use of the regression UI and
nothing in here has been needed, delete the whole `deprecated/` folder.
Until then, history is cheap; deletion is permanent.
