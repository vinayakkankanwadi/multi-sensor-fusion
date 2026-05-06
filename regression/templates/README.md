# Templates

One JSON file per SAPIENT message type. The UI auto-discovers these — adding a
new template means dropping a `.json` file here. **No code changes required.**

## Format

Each file is a SAPIENT `SapientMessage` rendered in protobuf JSON format
(google.protobuf.json_format), with the placeholders below substituted at
send time.

| Placeholder | Replaced with |
|---|---|
| `{{NOW}}` | Current UTC RFC3339 timestamp, e.g. `2026-05-03T12:34:56.000Z` |
| `{{ULID}}` | A freshly generated ULID. Each occurrence is independent. |
| `{{NODE_ID}}` | The UUID node_id configured in the UI. |

The exact JSON shape must follow the v2 protobuf
([`SAPIENT-Proto-Files/bsi_flex_335_v2_0/`](../../SAPIENT-Proto-Files/bsi_flex_335_v2_0/)).
The Windows reference harness's FluentValidation rules are stricter than
the .proto declares — see `deprecated/compat-baseline/edge-sim/driver/builders.py`
and the project's `reference_harness_quirks` memory for known gotchas
(e.g. `Registration.icd_version` must be `"BSI Flex 335 v2.0"` — with
spaces — and `mode_definition[].task.concurrent_tasks` must be set).

## Adding a new template

1. Copy any existing template, e.g. `cp registration.json my_new_message.json`.
2. Edit the `oneof content` block to your message.
3. Save. The UI will pick it up on the next page load — restart not needed
   because templates/ is mounted as a host volume.

## Editing in the UI

The UI loads the file as-is into a JSON editor. Anything you change in the
editor is sent verbatim (after placeholder substitution). The on-disk file
is not modified by the UI.
