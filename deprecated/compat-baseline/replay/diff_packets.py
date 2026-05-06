#!/usr/bin/env python3
"""diff_packets.py — diff outbound SAPIENT packets between a Windows-reference
baseline run and a new-middleware replay run for the same scenario.

Usage:
    ./diff_packets.py <baseline-dir>

Where <baseline-dir> contains:
    capture.pcap             from the Windows capture
    replay-<timestamp>.bin   produced by replay_pcap.py against the new middleware

Behavior (to implement):
    1. From capture.pcap, extract harness → client frames (the reference's
       outbound forwarded packets).
    2. From replay-*.bin, read the new middleware's outbound forwarded packets.
    3. Parse both as SapientMessage protobuf.
    4. Compare field-by-field, skipping fields documented as transport noise
       (top-level timestamps, transport-time ULID jitter, etc.) and fields
       documented as expected deltas (the new middleware does not apply
       CartesianOffset, etc.).
    5. Print a unified diff and exit non-zero if any unexpected delta is found.

Status: PLACEHOLDER.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <baseline-dir>", file=sys.stderr)
        return 2
    baseline_dir = Path(sys.argv[1])
    if not baseline_dir.is_dir():
        print(f"not a directory: {baseline_dir}", file=sys.stderr)
        return 2

    raise NotImplementedError(
        "diff_packets.py is a placeholder; implement the 5 steps in the module docstring."
    )


if __name__ == "__main__":
    sys.exit(main())
