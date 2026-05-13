# sapient-to-cot

A small Python package that turns SAPIENT BSI Flex 335 v2 messages into
Cursor-on-Target (CoT) XML events. Intended to be reused by:

- the **msf-ui** (`ui/`) when "Also send to TAK" is ticked
- the **future Python middleware** (`middleware/`) for transparent TAK fan-out
- the **future fusion node** (`fusion-node/`) for emitting fused tracks to TAK

The package itself is transport-agnostic — it just produces CoT XML bytes.
Sending them is the caller's job (see [`deprecated/tak-server-cot/cot.py`](../deprecated/tak-server-cot/cot.py)
for a UDP sender, or `ui/app/tak_bridge.py` for the in-UI fan-out).

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

xml = convert(msg, fallback_lat=-27.5037, fallback_lon=153.0924, fallback_alt=29.7)
if xml is not None:
    sock.sendto(xml, ("192.168.201.102", 6969))
```

## Tests

```bash
# from the repo root, with the ui venv that has proto bindings
deprecated/compat-baseline/edge-sim/.venv/bin/python -m pytest sapient-to-cot/tests -v
```

6 tests pass: each content-type mapping plus the "no CoT for unsupported
content" guard.

## Wired into the msf-ui

In the msf-ui's top toolbar, tick **Also send to TAK** to fan-out
every Send / Run flow to the TAK Server simultaneously. TAK host/port
come from the UI fields (default `192.168.201.102:6969` from
`MSF_TAK_HOST`/`MSF_TAK_PORT` env vars).

The result panel shows the TAK fan-out outcome alongside the middleware
result, e.g.:

```
20260503T_xxxxxx → sent registration, received 1 reply(ies)
   ·   TAK: sent 556B (a-f-G-U) → udp://192.168.201.102:6969
```
