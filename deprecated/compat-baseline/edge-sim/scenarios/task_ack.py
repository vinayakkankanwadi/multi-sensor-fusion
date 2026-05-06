"""Scenario: task_ack — emit a standalone TaskAck.

Sends a TaskAck with a freshly minted ULID task_id (i.e. not in response to
any real Task). Useful purely for protocol/wire baseline; the upstream may
treat it as an orphan ack.
"""

from __future__ import annotations

import logging

from driver import builders
from driver.client import SapientTcpClient
from driver.recorder import Recorder

from scenarios import registration as _registration

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    await _registration.run(client, recorder, ctx)

    msg = builders.task_ack(ctx.node_id)
    log.info("sending TaskAck task_id=%s", msg.task_ack.task_id)
    await client.send(msg)
    await client.drain_for(1.0)
