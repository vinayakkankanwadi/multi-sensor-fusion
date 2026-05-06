# Capture (Ubuntu side)

A runnable test harness that connects to a SAPIENT BSI Flex 335 v2 endpoint
(typically the Windows-hosted `SapientDataAgent` on its ASM-facing port,
default `14000`), drives a named scenario, and records both directions of
the wire conversation under `../baselines/<scenario>/<UTC-timestamp>/`.

The harness acts as the SAPIENT client (the role an ASM/edge node plays
when it talks to the Data Agent).

## One-time setup

```bash
cd compat-baseline/capture
./setup.sh
```

This creates `.venv/`, installs `protobuf`, `grpcio-tools`, `python-ulid`
and `pytest`, then generates `sapient_msg/` Python bindings from
`../../SAPIENT-Proto-Files/bsi_flex_335_v2_0/`. Re-run if those protos
change.

## Configuration

Either pass flags on the CLI or copy `env.example` to `env` and edit:

```
SAPIENT_HOST=192.0.2.10        # Windows host running the harness
SAPIENT_DA_PORT=14000          # SDA's ASM-facing listen port
BASELINES_DIR=../baselines
```

The harness's `app.config` must bind `ClientAddress=0.0.0.0` so it is
reachable from the LAN, and the Windows firewall must allow the port.

## Drive a scenario

```bash
. .venv/bin/activate
./drive_scenario.py --list                                     # list all scenarios
./drive_scenario.py registration                               # uses ./env defaults
./drive_scenario.py registration --host 192.0.2.10 --port 14000
./drive_scenario.py registration --node-id 11111111-1111-1111-1111-111111111111
```

A new directory is created under `BASELINES_DIR/<scenario>/<UTC-timestamp>/`
containing:

| File | Purpose |
|---|---|
| `sent.bin` | Raw length-prefixed bytes the driver emitted |
| `recv.bin` | Raw length-prefixed bytes received from the harness |
| `transcript.jsonl` | One decoded message per line, both directions, with millisecond offsets |
| `manifest.json` | Scenario, host, port, start/end UTC, status, repo git SHA |

These artifacts are what `../replay/` consumes when running the same
scenario against the new Python middleware.

## Scenarios available

All scenarios connect to the SDA's ASM-facing port as a SAPIENT client.
A background reader task drains and records every inbound frame, so any
unsolicited harness message (e.g. validation Errors) is captured even
when the scenario isn't actively waiting.

| Scenario | What it sends | What it captures |
|---|---|---|
| `registration` | Registration | RegistrationAck |
| `status` | Registration + 3 × StatusReport @ 5 s | RegistrationAck (and any unsolicited) |
| `detection` | Registration + StatusReport + 3 × DetectionReport | RegistrationAck |
| `alert` | Registration + Alert | RegistrationAck (+ AlertAck if DmmSim issues one) |
| `task_ack` | Registration + TaskAck (orphan) | RegistrationAck |
| `error_send` | Registration + Error (synthetic) | RegistrationAck |
| `error_recv` | Deliberately malformed Registration | Error (validator rejection) |
| `listen` | Registration + 6 s passive listen | RegistrationAck (+ Task if DmmSim issues one) |
| `shutdown` | Registration + StatusReport + StatusReport(SYSTEM_GOODBYE) | RegistrationAck |

## Message-type coverage

After running all scenarios, baselines exist for these `oneof content`
cases. The two gaps require fusion-side traffic from the DmmSim to be
configured to issue them — those captures will appear automatically once
the DmmSim is configured to task and to ack alerts.

| Message | Sent baseline | Received baseline |
|---|---|---|
| Registration | yes (every scenario) | n/a |
| RegistrationAck | n/a | yes (every scenario except `error_recv`) |
| StatusReport | yes (`status`, `detection`, `shutdown`) | n/a |
| DetectionReport | yes (`detection`) | n/a |
| Task | n/a | not yet (needs DmmSim issuing) |
| TaskAck | yes (`task_ack`) | n/a |
| Alert | yes (`alert`) | n/a |
| AlertAck | n/a | not yet (needs DmmSim responding) |
| Error | yes (`error_send`) | yes (`error_recv`) |

## Tests

```bash
. .venv/bin/activate
pytest tests/ -v
```

The framer tests run without any network or harness dependency.

## Optional: capture pcap alongside the driver

If you also want a packet-level capture to cross-check the recorder:

```bash
sudo tcpdump -i any -w /tmp/registration.pcap "host $SAPIENT_HOST and port $SAPIENT_DA_PORT" &
./drive_scenario.py registration
sudo pkill tcpdump
```

The harness's own `sent.bin`/`recv.bin` are usually sufficient — the pcap
is useful when investigating framing or TCP-level oddities.

## Layout

```
capture/
├── README.md
├── setup.sh                  one-time venv + proto generation
├── generate_proto.sh         regenerate sapient_msg/ from SAPIENT-Proto-Files
├── requirements.txt
├── env.example
├── drive_scenario.py         CLI entry point
├── driver/
│   ├── framer.py             4-byte LE length codec (spec §4.2)
│   ├── client.py             recording asyncio TCP client
│   ├── recorder.py           writes sent.bin/recv.bin/transcript.jsonl/manifest.json
│   └── builders.py           minimal-but-valid SapientMessage builders
├── scenarios/
│   ├── registration.py       implemented
│   ├── status.py             implemented
│   ├── detection.py          implemented
│   ├── alert.py              implemented (no DmmSim AlertAck yet)
│   ├── task_ack.py           implemented (orphan TaskAck)
│   ├── error_send.py         implemented (driver-emitted Error)
│   ├── error_recv.py         implemented (provokes harness Error)
│   ├── listen.py             implemented (passive Task wait)
│   └── shutdown.py           implemented
├── tests/
│   └── test_framer.py
└── sapient_msg/              generated; do not edit
```
