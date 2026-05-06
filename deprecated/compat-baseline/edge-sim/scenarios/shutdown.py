"""Scenario: shutdown (BSI Flex 335 v2 §4.8)."""

from __future__ import annotations

import logging

from sapient_msg.bsi_flex_335_v2_0 import status_report_pb2 as _stat

from driver import builders
from driver.client import SapientTcpClient
from driver.recorder import Recorder

from scenarios import registration as _registration

log = logging.getLogger(__name__)


async def run(client: SapientTcpClient, recorder: Recorder, ctx) -> None:
    await _registration.run(client, recorder, ctx)
    await client.send(builders.status_report(ctx.node_id))

    goodbye = builders.status_report(ctx.node_id, system=_stat.StatusReport.SYSTEM_GOODBYE)
    log.info("sending GOODBYE")
    await client.send(goodbye)
