"""Scenario: detection (BSI Flex 335 v2 §4.5 c)."""

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
    await client.send(builders.status_report(ctx.node_id))

    for i in range(3):
        msg = builders.detection_report(
            ctx.node_id,
            x=1.0 + i,
            y=2.0 + i,
            z=3.0 + i,
        )
        log.info("sending DetectionReport %d/3", i + 1)
        await client.send(msg)
        await asyncio.sleep(0.5)
