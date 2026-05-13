"""cot-bridge — SAPIENT → CoT → TAK fan-out service.

A single-purpose service. Accepts SAPIENT BSI Flex 335 v2 messages on a TCP
port (length-prefix protobuf, the same wire any SAPIENT consumer speaks),
converts each one to a Cursor-on-Target XML event using the shared
`sapient_to_cot` library, and sends it to a configured TAK Server over UDP.

It is intentionally **not** plumbed into anything yet. It stands alone so it
can be tested in isolation — feed it SAPIENT messages with a tiny TCP
client, watch CoT come out on the wire. Once it's proven, Apex's
`Parent forwardAll` connection points at this service on :5005.

Environment:
    MSF_COT_BRIDGE_BIND     listen address (default 0.0.0.0)
    MSF_COT_BRIDGE_PORT     listen port    (default 5005)
    MSF_TAK_HOST            TAK Server UDP host
    MSF_TAK_PORT            TAK Server UDP port (default 6969)
    MSF_FALLBACK_LAT        fallback latitude for messages without Location
    MSF_FALLBACK_LON        fallback longitude
    MSF_FALLBACK_ALT        fallback altitude (m, default 0.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Optional

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

import sapient_to_cot

from . import framer


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("cot-bridge")


def _env_float(name: str) -> Optional[float]:
    v = os.environ.get(name, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


BIND      = os.environ.get("MSF_COT_BRIDGE_BIND", "0.0.0.0")
PORT      = int(os.environ.get("MSF_COT_BRIDGE_PORT", "5005"))
TAK_HOST  = os.environ.get("MSF_TAK_HOST", "192.168.201.222")
TAK_PORT  = int(os.environ.get("MSF_TAK_PORT", "6969"))
FB_LAT    = _env_float("MSF_FALLBACK_LAT")
FB_LON    = _env_float("MSF_FALLBACK_LON")
FB_ALT    = _env_float("MSF_FALLBACK_ALT") or 0.0


_stats = {
    "frames_in": 0,
    "cot_out": 0,
    "skipped_no_position": 0,
    "skipped_no_mapping": 0,
    "send_errors": 0,
}


def _convert_and_send(msg: _msg.SapientMessage) -> None:
    content = msg.WhichOneof("content")
    xml = sapient_to_cot.convert(
        msg, fallback_lat=FB_LAT, fallback_lon=FB_LON, fallback_alt=FB_ALT,
    )
    if xml is None:
        if content in ("registration", "status_report", "detection_report", "alert"):
            _stats["skipped_no_position"] += 1
            log.info("skipped %s (no position; set MSF_FALLBACK_LAT/LON or include Location)",
                     content)
        else:
            _stats["skipped_no_mapping"] += 1
            log.info("skipped %s (no CoT mapping for this content type)", content)
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(xml, (TAK_HOST, TAK_PORT))
        _stats["cot_out"] += 1
        log.info("sent CoT %dB → udp://%s:%d (from sapient %s)",
                 len(xml), TAK_HOST, TAK_PORT, content)
    except OSError as exc:
        _stats["send_errors"] += 1
        log.warning("send to TAK failed: %s", exc)
    finally:
        sock.close()


async def handle_client(reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    log.info("client connected from %s", peer)
    try:
        async for payload in framer.read_frames(reader):
            _stats["frames_in"] += 1
            msg = _msg.SapientMessage()
            try:
                msg.ParseFromString(payload)
            except Exception as exc:
                log.warning("parse failed from %s: %s", peer, exc)
                continue
            log.info("recv %s (%d bytes, node=%s…)",
                     msg.WhichOneof("content"), len(payload), msg.node_id[:8])
            _convert_and_send(msg)
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


async def _stats_ticker() -> None:
    while True:
        await asyncio.sleep(30)
        log.info("stats: %s", _stats)


async def main() -> None:
    server = await asyncio.start_server(handle_client, BIND, PORT)
    log.info("cot-bridge listening on %s:%d (TAK target udp://%s:%d, fallback lat=%s lon=%s)",
             BIND, PORT, TAK_HOST, TAK_PORT, FB_LAT, FB_LON)
    async with server:
        asyncio.create_task(_stats_ticker())
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
