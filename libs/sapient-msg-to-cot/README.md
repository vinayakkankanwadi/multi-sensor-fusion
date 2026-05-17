# sapient-msg-to-cot

Convert SAPIENT BSI Flex 335 v2 protobuf messages into Cursor-on-Target
(CoT) XML events. Transport-agnostic — `convert()` returns CoT XML bytes
(or `None` if there's no mapping or no usable position), and the caller
decides how to ship them.

Today the only consumer is [`services/cot-bridge/`](../../services/cot-bridge/),
which receives SAPIENT over TCP and UDP-sends the CoT output to a TAK
Server. Future consumers (e.g. a fusion node emitting fused tracks)
should use it the same way.

## Layout

```
sapient-msg-to-cot/
├── README.md
├── pyproject.toml
└── sapient_msg_to_cot/      importable Python package
    ├── __init__.py
    └── converter.py
```

Tests live alongside the other regression suites at
[`tests/libs/sapient_msg_to_cot/`](../../tests/libs/sapient_msg_to_cot/).

## Mappings

| SAPIENT content     | CoT type          | Position source |
|---------------------|-------------------|-----------------|
| Registration        | per `node_type` (radar → `a-f-G-E-S-R`, camera → `a-f-G-E-S-E`, etc.) | fallback (e.g. live GPS) |
| StatusReport        | `a-f-G-U` (friendly ground)              | `node_location` if set, else fallback |
| DetectionReport     | `a-u-G` (unknown ground)                 | `location` if set, else fallback |
| Alert               | `a-h-G` (hostile ground)                 | `location` if set, else fallback |
| Task / TaskAck / AlertAck / RegistrationAck / Error | (no CoT) | n/a |

If a message has no position **and** no fallback was supplied, the
converter returns `None` — callers should not push positionless events
to TAK.

## Usage

```python
from sapient_msg_to_cot import convert
from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as M

msg = M.SapientMessage()
# ... populate msg ...

xml = convert(msg, fallback_lat=-27.4698, fallback_lon=153.0251, fallback_alt=27.0)
if xml is not None:
    sock.sendto(xml, ("192.168.201.222", 6969))
```

## How cot-bridge uses it

[`services/cot-bridge/`](../../services/cot-bridge/) accepts SAPIENT
length-prefix protobuf on TCP `:5005`, calls
`convert(msg, fallback_lat=…, fallback_lon=…, fallback_alt=…)`, and
UDP-sends the XML to `TAK_HOST:TAK_PORT`. Apex's outbound Parent
`forwardAll` connection points at `127.0.0.1:5005` (see
[`services/apex/apex_config.json`](../../services/apex/apex_config.json)),
so any SAPIENT message landing on Apex from a Child or Peer is
automatically mirrored as CoT on the map. Messages with no CoT mapping
(e.g. `registration_ack`) return `None` and cot-bridge bumps its
`skipped_no_mapping` counter.
