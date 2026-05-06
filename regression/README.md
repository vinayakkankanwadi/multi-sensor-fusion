# msf-regression-ui

A Docker-packaged web UI for sending any SAPIENT BSI Flex 335 v2 message
template to a configurable IP/port and inspecting the wire conversation.
Used as a regression suite against the Windows reference harness, and
later against the new Python middleware as it comes online.

The whole thing is **template-driven**: adding a new SAPIENT message type
is a matter of dropping a `.json` file under [`templates/`](templates/) on
the host. The container picks it up on the next page load — **no rebuild,
no Python changes**.

## Layout

```
regression/
├── README.md             this file
├── Dockerfile            python:3.12-slim + grpc_tools (proto codegen at build time)
├── docker-compose.yml    one service, host networking, templates/ + runs/ as volumes
├── requirements.txt
├── .gitignore            ignores generated bindings + transcripts
├── app/
│   ├── main.py           FastAPI: /api/templates, /api/send, /api/runs, /api/health
│   ├── framer.py         spec §4.2 — 4-byte little-endian length prefix
│   ├── templates_loader.py   discovery, placeholder substitution, JSON->protobuf parse
│   ├── runner.py         async TCP client, send + drain + transcript
│   └── static/           single-page UI (no SPA framework)
├── templates/            mounted volume — drop .json here
│   ├── registration.json    spec §6.2 — minimal compliant Registration
│   ├── status_report.json   spec §6.3
│   ├── detection_report.json spec §6.4
│   ├── alert.json           spec §6.6
│   ├── alert_ack.json       spec §6.6
│   ├── task_ack.json        spec §6.5
│   ├── error.json           spec §6.7
│   └── README.md
├── sapient_msg/          generated bindings (built into image; gitignored)
└── runs/                 mounted volume — per-run JSON transcripts
```

## Step-by-step: bring it up

```bash
cd regression
docker compose build         # ~30s; bakes proto bindings into the image
docker compose up -d
```

Open http://localhost:8080 in your browser.

## Step-by-step: send a Registration

1. Top bar → set **Host** (e.g. `192.168.201.152`) and **Port** (`14000` for
   the SDA's ASM-facing port). Settings persist in browser localStorage.
2. **Node UUID** is auto-generated. Click **New UUID** to get a fresh one.
3. Left sidebar → click **registration**.
4. Editor shows the JSON. The `{{NOW}}`, `{{NODE_ID}}`, `{{ULID}}`
   placeholders are substituted at send time.
5. Click **Send**.
6. **Result** pane shows the transcript:
   - `sent` line: the Registration we serialised and framed.
   - `recv` lines: any reply from the harness (typically `registration_ack`,
     or `error` if validation failed).
7. Recent runs appear at the bottom; click any to re-display its transcript.
   Run JSON also lands under `regression/runs/<run_id>/result.json` on the host.

## Step-by-step: edit before sending

The textarea contains the full SapientMessage JSON. Change anything you
want — add fields, tweak enum values, swap units. Click **Send** to push
the edited body. The on-disk template is **not** modified by edits in the
UI. Click **Reload from disk** to discard your edits.

## Step-by-step: regenerate templates from .proto

The handwritten templates are gone — they're auto-generated from the
SAPIENT v2 .proto descriptors plus a small "validator quirks" table
(`app/proto_to_template.py`). To rebuild:

```bash
docker exec msf-regression-ui python -m app.proto_to_template --out /app/templates
```

Or click **Regenerate templates from .proto** in the UI top bar.

The converter walks `SapientMessage.content`, picks each oneof case in turn,
and recursively populates every field marked `is_mandatory` in the .proto
plus the validator-only quirks (Registration `icd_version` literal,
StatusReport `mode`, TaskDefinition `concurrent_tasks`). Output is
google.protobuf JSON with `{{NOW}}`, `{{NODE_ID}}`, `{{ULID}}` placeholders
substituted at send time.

If a future BSI Flex revision adds, removes, or reshapes a message,
re-run the converter — no Python edits needed.

## Step-by-step: validate-only (no send)

Tick **Validate before send** in the UI; the body is run through the
client-side validator (`app/validators.py`) before it goes on the wire.
Failures show up in the result pane with the specific FluentValidation rule
that would have rejected the message at the harness. Click **Validate only**
to run the validator without ever opening a TCP connection.

The same validator runs in the backend's `POST /api/validate`, so any
JSON-driven workflow can use it.

## Step-by-step: GPS from the router

If the router exposes a GPS module via the RutOS REST API, the regression UI
can pull the live fix and show it in the Clock-sync panel **and** substitute
it into templates as `{{GPS_LAT}}`, `{{GPS_LON}}`, `{{GPS_ALT}}` — the same
way `{{NODE_ID}}` and `{{NOW}}` work.

The router needs admin credentials, so set them as host env vars (never
typed into the browser):

```bash
export MSF_ROUTER_USER=admin
export MSF_ROUTER_PASS='<your router password>'
docker compose up -d   # picks up the env vars from your shell
```

Then in any template you want geolocated, replace fixed numbers with
placeholders, e.g. for a Detection report:

```json
"location": {
  "x": {{GPS_LAT}},
  "y": {{GPS_LON}},
  "z": {{GPS_ALT}},
  "coordinate_system": "LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M",
  "datum": "LOCATION_DATUM_WGS84_E"
}
```

Test directly:

```bash
curl -s http://localhost:8080/api/gps | jq
```

If credentials aren't set you'll get a clear "router credentials not
configured" error rather than a guess. The UI's Clock-sync panel shows the
GPS row with the same explanation.

## Step-by-step: NTP sync check

The header carries a small `ntp:` badge that pings `pool.ntp.org` (override
with `MSF_NTP_SERVER` env var) and shows the local clock offset. Spec §4.1
requires NTP-synced clocks; the harness validators fail unhelpfully if your
machine is more than a couple seconds off.

| Severity | Threshold | Badge color |
|---|---|---|
| `ok`   | offset < 0.5 s | green |
| `warn` | 0.5–2 s        | yellow |
| `fail` | ≥ 2 s          | red |

`GET /api/ntp` returns the same data as JSON for scripted checks.

## Step-by-step: add a new message template

```bash
cd regression/templates
cp status_report.json my_new_status.json
$EDITOR my_new_status.json    # tweak fields, set the right oneof content
# no need to restart — templates/ is mounted live
```

Reload the browser. The new template name appears in the sidebar.
The format is google.protobuf.json_format encoding of `SapientMessage`
(see [templates/README.md](templates/README.md) for placeholders and the
known FluentValidator quirks the .proto doesn't capture).

## Verified end-to-end (today)

Smoke-tested against a local Python stub (the Windows host at
`192.168.201.152:14000` was offline at the time):

```
=== /api/send template=registration ===
  run_id: 20260503T030719_a2f97e   error: None
    t=    0.1ms  sent  registration       (171b)
    t=    0.7ms  recv  registration_ack   (102b)
=== /api/send template=status_report ===
    t=    0.1ms  sent  status_report      ( 95b)
    t=    0.5ms  recv  registration_ack   (103b)
... (every other template round-trips identically)
```

Adding a `custom_demo.json` file under `templates/` on the host while the
container was running made it appear in the next `GET /api/templates` —
confirming live template discovery without restart.

## Tests

Unit tests live in `tests/` and are baked into the image so they can run
inside the container without a venv:

```bash
docker exec msf-regression-ui pytest /app/tests -q     # 24 passed
```

Coverage:

| File | What it tests |
|---|---|
| `tests/test_framer.py` | spec §4.2 length-prefix codec, async + truncation |
| `tests/test_proto_to_template.py` | converter generates one template per content case; each parses back; each passes the client-side validator; quirks (`icd_version`, `mode`, `concurrent_tasks`) are present |
| `tests/test_validators.py` | every per-message validator catches its known mandatory-field violations |
| `tests/test_ntp.py` | severity classification, short-reply / network-error handling, synthetic in-sync server. Set `MSF_NTP_LIVE=1` to also hit a real server. |

## End-to-end UI test

A headless smoke runner exercises every UI flow over HTTP — useful for CI
and for validating an image after a rebuild:

```bash
./scripts/headless_ui_test.sh
```

It checks: HTML + assets load; `/api/health`; `/api/templates` returns the
expected count; client-side validator accepts a good template and rejects a
template with `icd_version` corrupted; NTP probe; round-trip every one of
the 9 templates against a local stub; recent-runs API.

## API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Single-page UI |
| GET | `/api/health` | `{"ok":true,"templates":[...]}` |
| GET | `/api/templates` | Discovered templates with raw JSON + decoded preview |
| GET | `/api/templates/{name}` | One template's raw JSON |
| POST | `/api/templates/regenerate` | Re-run the proto-to-template converter |
| POST | `/api/validate` | Body: `{node_id, template_name?, raw_json?}` → `{ok, errors[]}` |
| POST | `/api/send` | Body: `{host,port,node_id,template_name,raw_json?,recv_timeout_s?,drain_after_s?,validate_before_send?}` → transcript |
| GET | `/api/runs` | Latest 50 runs (summary) |
| GET | `/api/runs/{run_id}` | Full transcript JSON |
| GET | `/api/ntp?server=&timeout=` | Probe NTP server, return offset + severity |

## Networking

The container uses **host networking** (`network_mode: host`) so it can
reach LAN peers (e.g. the Windows BSI Flex Test Harness) without docker-bridge
NAT. Side effect: the UI is bound to `host:8080` directly — no `ports:`
mapping is needed. If port 8080 is taken on your host, change the
`uvicorn ... --port 8080` line in the Dockerfile and rebuild.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `connect failed: [Errno 113] No route to host` | The target IP is unreachable. Check it with `ping` from the host (the container shares the host network stack). |
| `connect failed: [Errno 111] Connection refused` | Target port has no listener. Confirm the harness is running. |
| Template not appearing in the sidebar | Reload the browser — `/api/templates` is read on each load. If still missing, `docker logs msf-regression-ui` will show JSON parse errors. |
| `template parse failed: ...` on send | The JSON doesn't match the `SapientMessage` schema. Common cause: invalid enum spelling. |
| Harness sends back an `error` reply | Validator rejected the message. The error transcript will list the specific FluentValidation failures. See `deprecated/compat-baseline/edge-sim/driver/builders.py` for known-good builders that pass the reference validators. |
