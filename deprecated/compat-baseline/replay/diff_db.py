#!/usr/bin/env python3
"""diff_db.py — diff Postgres state in the new middleware against the reference
Windows harness baseline for one scenario.

Usage:
    ./diff_db.py <baseline-dir>

Where <baseline-dir> contains:
    postgres.dump   pg_dump (custom format) of the Windows reference DB

Behavior (to implement):
    1. Restore postgres.dump into a throwaway Postgres database.
    2. Connect to the new middleware's database (env: PG* vars).
    3. For each table that exists in both schemas, diff row counts and
       sample-row content; treat the reference's "Zodiac" tables (objective,
       route_plan) and sensor_location_offset as "expected absent" in the
       new schema, not failures.
    4. Print per-table summary; exit non-zero on any unexpected delta.

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
        "diff_db.py is a placeholder; implement the 4 steps in the module docstring."
    )


if __name__ == "__main__":
    sys.exit(main())
