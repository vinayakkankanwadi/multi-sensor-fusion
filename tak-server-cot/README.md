# tak-server-cot

Minimal Python sender for **Cursor-on-Target (CoT)** messages over UDP to a
TAK Server (or any CoT listener). Used to project SAPIENT-derived entities
(detections, edge nodes, fusion tracks) onto an ATAK / WinTAK / iTAK map.

## Layout

```
tak-server-cot/
├── README.md      this file
└── cot.py         CoT XML builder + UDP sender (CLI + importable)
```

## Quick start

```bash
cd tak-server-cot

# show the XML it would send (no network)
python3 cot.py --print --host 0.0.0.0 --callsign DEMO --remarks "preview only"

# send one message to the TAK server on UDP/6969
python3 cot.py --host 192.168.201.102 --port 6969 \
               --callsign MSF-Edge-1 --lat -27.503742 --lon 153.092451 \
               --hae 29.7 --remarks "hello from msf"

# send 10 copies, 1 s apart (e.g. fake heartbeat)
python3 cot.py --host 192.168.201.102 --port 6969 \
               --callsign MSF-Edge-1 --uid MSF-EDGE-1 --repeat 10 --interval 1
```

Verified live against `192.168.201.102:6969` from this machine — both sends
returned the byte count (532 B and 503 B respectively) without socket error.

To confirm the map icon appeared, check the ATAK/WinTAK client connected
to that TAK server, or the TAK server admin map.

## Connection details

| Setting | Value |
|---|---|
| TAK server | 192.168.201.102 |
| Port       | 6969 (UDP) |
| Protocol   | CoT XML, no SSL |

The default 8087 (TCP) and 8089 (TLS) TAK ports use a different transport.
This sender talks only **UDP**; switch to TCP/TLS later if your TAK Server
config requires it.

## CoT type cheatsheet

`event.type` follows MIL-STD-2525:

| Type            | Meaning                                  |
|-----------------|------------------------------------------|
| `a-f-G-U-C`     | Atom · Friend · Ground · Unit · Combat   |
| `a-f-G-E-V-C`   | Atom · Friend · Ground · Equipment · Vehicle · Combat |
| `a-h-G-U-C`     | Atom · Hostile · Ground · Unit · Combat  |
| `a-n-G`         | Atom · Neutral · Ground                  |
| `a-u-G`         | Atom · Unknown · Ground                  |
| `a-f-A-M-F`     | Friend Air Manned Fighter                |

Pass via `--type`. Default is `a-f-G-U-C` (friendly ground unit combat).

## Importable

```python
from cot import build_cot, send_udp

xml = build_cot(uid="MSF-Edge-1", lat=-27.503742, lon=153.092451,
                hae=29.7, callsign="MSF-Edge-1", remarks="ground truth")
send_udp(xml, "192.168.201.102", 6969)
```

## Roadmap (out of scope here, just listed for orientation)

- Bridge: subscribe to SAPIENT detection_report messages from the new
  Python middleware, transform each detection into a CoT event, and push
  to TAK. That belongs in a separate `sapient-cot-bridge` service once the
  middleware lands.
- TLS/TCP transport for production TAK Servers that don't allow plaintext UDP.
- Server-time-synced staleness from the same NTP source as the rest of
  the stack (router 192.168.201.1).
