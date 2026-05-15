# sapient-to-cot

A small Python package that turns SAPIENT BSI Flex 335 v2 messages into
Cursor-on-Target (CoT) XML events. The package is **transport-agnostic**
— `convert()` returns CoT XML bytes (or `None` if there's no mapping or
no usable position), and the caller decides how to ship them.

Today the only consumer is [`cot-bridge/`](../cot-bridge/) — a standalone
SAPIENT → CoT → TAK fan-out service that's plugged into Apex's outbound
Parent `forwardAll`. It vendors this package in via Docker build context
so there's no PyPI install step.

Future consumers expected to use it the same way:

- a **fusion node** emitting fused tracks to TAK
- any other downstream SAPIENT sink that wants CoT output

## Layout

```
sapient-to-cot/
├── README.md
├── sapient_to_cot/        importable Python package
│   ├── __init__.py
│   └── converter.py
└── tests/
    └── test_converter.py
```

## Mappings

| SAPIENT content     | CoT type          | Position source |
|---------------------|-------------------|-----------------|
| Registration        | per `node_type` (radar → `a-f-G-E-S-R`, camera → `a-f-G-E-S-E`, etc.) | fallback (e.g. live GPS) |
| StatusReport        | `a-f-G-U` (friendly ground)              | `node_location` if set, else fallback |
| DetectionReport     | `a-u-G` (unknown ground)                 | `location` if set, else fallback |
| Alert               | `a-h-G` (hostile ground)                 | `location` if set, else fallback |
| Task / TaskAck / AlertAck / RegistrationAck / Error | (no CoT) | n/a |

If a message has no position **and** no fallback was supplied, the converter
returns `None` — the caller should not push positionless events to TAK.

## Usage

```python
from sapient_to_cot import convert
from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as M

msg = M.SapientMessage()
# ... populate msg ...

xml = convert(msg, fallback_lat=-27.4698, fallback_lon=153.0251, fallback_alt=27.0)
if xml is not None:
    sock.sendto(xml, ("192.168.201.222", 6969))
```

## Tests

The cot-bridge image installs `pytest` and bakes this package alongside
the rest of its source, so the simplest way to run the tests is from
inside that container:

```bash
docker exec cot-bridge python -m pytest /app/sapient_to_cot -v
```

Tests cover each content-type mapping plus the "no CoT for unsupported
content" guard. To run on the host you need a venv with the v2 proto
bindings on `PYTHONPATH`; the [`cot-bridge/Dockerfile`](../cot-bridge/Dockerfile)
shows how those bindings are produced from the .proto files.

## How cot-bridge uses it

[`cot-bridge/`](../cot-bridge/) accepts SAPIENT length-prefix protobuf
on TCP `:5005`, calls `convert(msg, fallback_lat=…, fallback_lon=…,
fallback_alt=…)`, and UDP-sends the XML to `TAK_HOST:TAK_PORT`.
Apex's outbound Parent `forwardAll` connection points at `127.0.0.1:5005`
(see [`apex/apex_config.json`](../apex/apex_config.json)), so any
SAPIENT message landing on Apex from a Child or Peer is automatically
mirrored as CoT on the map. Messages with no CoT mapping (e.g.
`registration_ack`) return `None` and cot-bridge bumps its
`skipped_no_mapping` counter.
