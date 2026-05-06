#!/usr/bin/env python3
"""drive_scenario.py — drive one baseline-capture scenario from Ubuntu against
a running SAPIENT BSI Flex 335 v2 endpoint (typically a Windows-hosted
SapientDataAgent).

Usage:
    drive_scenario.py <scenario> [--host HOST] [--port PORT] [--node-id UUID]
                                 [--baselines-dir DIR] [--recv-timeout SEC]
                                 [--list]

Defaults are read from ./env (KEY=VALUE lines; see env.example) if present;
CLI flags override the env file.

Run from compat-baseline/capture/ with the venv active:
    . .venv/bin/activate
    ./drive_scenario.py registration --host 192.0.2.10 --port 14000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Make `driver`, `scenarios`, and `sapient_msg` importable when run as a script.
sys.path.insert(0, str(HERE))


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _resolve(env: dict[str, str], key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or env.get(key) or default


async def _run(scenario: str, host: str, port: int, node_id: str,
               baselines_dir: Path, recv_timeout: float) -> int:
    from driver.client import SapientTcpClient
    from driver.recorder import Recorder
    from scenarios import Context, get

    fn = get(scenario)

    log = logging.getLogger("drive_scenario")
    log.info("scenario=%s host=%s port=%d node_id=%s", scenario, host, port, node_id)

    with Recorder(baselines_dir, scenario, host, port) as rec:
        client = SapientTcpClient(host, port, rec)
        try:
            await client.connect()
        except (OSError, asyncio.TimeoutError) as exc:
            log.error("connect failed: %s", exc)
            rec.close("error", note=f"connect: {exc}")
            return 1
        try:
            ctx = Context(node_id=node_id, recv_timeout_s=recv_timeout)
            await fn(client, rec, ctx)
            log.info("scenario complete; baseline at %s", rec.dir)
            return 0
        except NotImplementedError as exc:
            log.error("scenario not implemented: %s", exc)
            return 2
        except Exception as exc:
            log.exception("scenario failed: %s", exc)
            return 1
        finally:
            await client.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("scenario", nargs="?", help="scenario name (use --list to see all)")
    p.add_argument("--host", help="SAPIENT endpoint host (env: SAPIENT_HOST)")
    p.add_argument("--port", type=int,
                   help="SAPIENT endpoint port (env: SAPIENT_DA_PORT)")
    p.add_argument("--node-id", help="UUID node_id to register as (env: SAPIENT_NODE_ID)")
    p.add_argument("--baselines-dir",
                   help="output root (env: BASELINES_DIR; default: ../baselines)")
    p.add_argument("--recv-timeout", type=float, default=10.0,
                   help="seconds to wait for inbound replies (default 10)")
    p.add_argument("--list", action="store_true", help="list available scenarios and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.list:
        from scenarios import REGISTRY
        for name in sorted(REGISTRY):
            print(name)
        return 0

    if not args.scenario:
        p.error("scenario name required (or use --list)")

    env = _load_env_file(HERE / "env")
    host = args.host or _resolve(env, "SAPIENT_HOST")
    port = args.port or int(_resolve(env, "SAPIENT_DA_PORT") or 0)
    node_id = args.node_id or _resolve(env, "SAPIENT_NODE_ID") or str(uuid.uuid4())
    baselines_dir = Path(
        args.baselines_dir
        or _resolve(env, "BASELINES_DIR")
        or (HERE.parent / "baselines")
    ).resolve()

    if not host or not port:
        p.error("host and port required (CLI flags or env file)")

    return asyncio.run(_run(
        args.scenario, host, port, node_id, baselines_dir, args.recv_timeout
    ))


if __name__ == "__main__":
    sys.exit(main())
