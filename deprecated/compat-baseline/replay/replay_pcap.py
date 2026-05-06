#!/usr/bin/env python3
"""replay_pcap.py — replay captured SAPIENT client traffic against the new
local middleware container.

Usage:
    ./replay_pcap.py <path-to-capture.pcap>

Behavior (to implement):
    1. Load the pcap (scapy or pyshark).
    2. Identify TCP streams to/from the configured Windows host on the
       SAPIENT ports. Pick the client → harness direction.
    3. Reassemble each TCP stream and split it into 4-byte-LE-length
       SapientMessage frames per spec §4.2.
    4. Open a TCP connection to localhost on the new middleware's
       edge-facing port and re-emit each frame in order, preserving the
       original inter-frame timing (configurable: --asap to ignore timing).
    5. Capture the middleware's outbound responses; write them next to the
       input pcap as "replay-<timestamp>.bin" for diff_packets.py to pick up.

Status: PLACEHOLDER. Wire up after the middleware container exposes its
edge-facing port and at least one scenario has a captured baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-capture.pcap>", file=sys.stderr)
        return 2
    pcap = Path(sys.argv[1])
    if not pcap.exists():
        print(f"not found: {pcap}", file=sys.stderr)
        return 2

    raise NotImplementedError(
        "replay_pcap.py is a placeholder; implement the 5 steps in the module docstring."
    )


if __name__ == "__main__":
    sys.exit(main())
