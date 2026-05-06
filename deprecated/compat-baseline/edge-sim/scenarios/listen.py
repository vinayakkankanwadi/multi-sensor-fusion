"""Scenario: listen — passively wait for unsolicited inbound messages.

Registers, then sits with the connection open for `recv_timeout_s` to give
the upstream (DmmSim) a chance to issue a Task or other message. Anything
received is captured by the background reader.
"""

from __future__ import annotations

import logging

from driver.client import SapientTcpClient
from driver.recorder import Recorder

from scenarios import registration as _registration

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    await _registration.run(client, recorder, ctx)
    log.info("listening for %.1fs", ctx.recv_timeout_s)
    await client.drain_for(ctx.recv_timeout_s)
