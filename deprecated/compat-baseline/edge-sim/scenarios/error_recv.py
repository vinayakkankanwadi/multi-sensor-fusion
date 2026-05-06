"""Scenario: error_recv — provoke the harness to send an Error back.

Sends a deliberately-broken Registration (missing icd_version) to elicit
an Error response from the SapientMainMessageValidator path.
"""

from __future__ import annotations

import logging

from driver import builders
from driver.client import SapientTcpClient
from driver.recorder import Recorder

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    msg = builders.registration(ctx.node_id, icd_version="")
    msg.registration.ClearField("icd_version")
    log.info("sending Registration with icd_version cleared (expected to be rejected)")
    await client.send(msg)
    err = await client.expect("error", timeout=ctx.recv_timeout_s)
    log.info("got Error: %s", list(err.error.error_message))
