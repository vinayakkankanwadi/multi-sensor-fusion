"""Scenario: status (BSI Flex 335 v2 §4.5 b)."""

from __future__ import annotations

import asyncio
import logging

from driver import builders
from driver.client import SapientTcpClient
from driver.recorder import Recorder

from scenarios import registration as _registration

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    await _registration.run(client, recorder, ctx)
    for i in range(3):
        msg = builders.status_report(ctx.node_id)
        log.info("sending StatusReport %d/3", i + 1)
        await client.send(msg)
        await asyncio.sleep(5.0)
