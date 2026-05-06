"""Scenario: error_send — emit a standalone Error message.

Sends a SapientMessage{content=Error} that wraps a synthetic bad packet,
to capture the wire bytes for the Error oneof case.
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

    msg = builders.error(
        ctx.node_id,
        bad_packet=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        messages=["compat-baseline synthetic error"],
    )
    log.info("sending Error message")
    await client.send(msg)
    await client.drain_for(1.0)
