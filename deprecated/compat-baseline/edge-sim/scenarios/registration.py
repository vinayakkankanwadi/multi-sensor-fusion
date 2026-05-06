"""Scenario: registration (BSI Flex 335 v2 §4.4).

Driver acts as an edge node. Sends one Registration; waits for one
RegistrationAck; closes the connection.
"""

from __future__ import annotations

import logging

from driver import builders
from driver.client import SapientTcpClient
from driver.recorder import Recorder

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    msg = builders.registration(ctx.node_id)
    log.info("sending Registration node_id=%s", ctx.node_id)
    await client.send(msg)

    log.info("awaiting RegistrationAck (timeout %.1fs)", ctx.recv_timeout_s)
    reply = await client.recv(timeout=ctx.recv_timeout_s)
    content = reply.WhichOneof("content")
    log.info("got reply content=%s node_id=%s", content, reply.node_id)
    if content != "registration_ack":
        raise RuntimeError(f"expected registration_ack, got {content}")
