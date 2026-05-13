"""sapient — Linux SAPIENT BSI Flex 335 v2 service (in development).

Listens on TCP for length-prefixed SapientMessage frames, decodes them,
and responds per spec where a reply is mandatory:

  Registration   → RegistrationAck (acceptance=true)
  Status / Detection / Alert / TaskAck / Error / AlertAck → accept silently (logged)

This is the seed for the new middleware. It deliberately starts as a happy-
path responder so the msf-ui has a Linux-side counterpart to exercise.
Real validation, persistence, fan-out, and ASM/fusion routing get layered on
top as we go.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from sapient_msg.bsi_flex_335_v2_0 import (
    registration_ack_pb2 as _reg_ack,  # noqa: F401
    sapient_message_pb2 as _msg,
)

from . import framer

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("sapient")

HOST = os.environ.get("MSF_SAPIENT_BIND", "0.0.0.0")
PORT = int(os.environ.get("MSF_SAPIENT_PORT", "14000"))
NODE_ID = os.environ.get("MSF_SAPIENT_NODE_ID",
                         "00000000-0000-4000-8000-00000000ffff")


def _now_ts(ts) -> None:
    t = datetime.now(timezone.utc)
    ts.seconds = int(t.timestamp())
    ts.nanos = (int(t.timestamp() * 1e6) % 1_000_000) * 1000


def build_registration_ack(req: _msg.SapientMessage) -> _msg.SapientMessage:
    out = _msg.SapientMessage()
    _now_ts(out.timestamp)
    out.node_id = NODE_ID
    out.destination_id = req.node_id
    out.registration_ack.acceptance = True
    out.registration_ack.ack_response_reason.append("accepted (sapient)")
    return out


async def handle_client(reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    log.info("client connected from %s", peer)
    try:
        async for payload in framer.read_frames(reader):
            msg = _msg.SapientMessage()
            try:
                msg.ParseFromString(payload)
            except Exception as exc:
                log.warning("parse failed from %s: %s", peer, exc)
                continue

            content = msg.WhichOneof("content")
            log.info("%s → recv %s (%d bytes, node=%s…)",
                     peer, content, len(payload), msg.node_id[:8])

            if content == "registration":
                ack = build_registration_ack(msg)
                out = ack.SerializeToString()
                writer.write(framer.encode(out))
                await writer.drain()
                log.info("%s ← send registration_ack (%d bytes)",
                         peer, len(out))
            # Other content types accepted silently — spec §4.5/§4.6.
    except asyncio.IncompleteReadError:
        log.info("client %s disconnected", peer)
    except Exception:
        log.exception("error on connection from %s", peer)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(handle_client, HOST, PORT)
    log.info("sapient listening on %s:%d (node_id=%s)", HOST, PORT, NODE_ID)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
