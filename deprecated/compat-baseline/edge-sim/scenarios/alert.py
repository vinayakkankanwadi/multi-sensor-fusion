"""Scenario: alert (BSI Flex 335 v2 §4.6).

Driver registers, then sends one Alert; waits briefly for an inbound
AlertAck (the upstream DmmSim/fusion typically issues these).
"""

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

    msg = builders.alert(ctx.node_id)
    alert_id = msg.alert.alert_id
    log.info("sending Alert alert_id=%s", alert_id)
    await client.send(msg)

    try:
        ack = await client.expect("alert_ack", timeout=ctx.recv_timeout_s)
        log.info("got AlertAck status=%s alert_id=%s",
                 ack.alert_ack.alert_ack_status, ack.alert_ack.alert_id)
    except asyncio.TimeoutError:
        log.info("no AlertAck within %.1fs (DmmSim may not be issuing)",
                 ctx.recv_timeout_s)
    # Small drain window so any unsolicited error surfaces in recv.bin.
    await client.drain_for(1.0)
