"""cot-bridge — SAPIENT → CoT → TAK fan-out service.

A single-purpose service. Accepts SAPIENT BSI Flex 335 v2 messages on a TCP
port (length-prefix protobuf, the same wire any SAPIENT consumer speaks),
converts each one to a Cursor-on-Target XML event using the shared
`sapient_msg_to_cot` library, and sends it to a configured TAK Server over UDP.

It is intentionally **not** plumbed into anything yet. It stands alone so it
can be tested in isolation — feed it SAPIENT messages with a tiny TCP
client, watch CoT come out on the wire. Once it's proven, Apex's
`Parent forwardAll` connection points at this service on :5005.

Environment:
    COT_BRIDGE_BIND       listen address (default 0.0.0.0)
    COT_BRIDGE_PORT       SAPIENT TCP listen port    (default 5005)
    COT_BRIDGE_HTTP_PORT  HTTP /health + /stats port (default 8092)
    TAK_HOST              TAK Server UDP host
    TAK_PORT              TAK Server UDP port (default 6969)
    FALLBACK_LAT          fallback latitude for messages without Location
    FALLBACK_LON          fallback longitude
    FALLBACK_ALT          fallback altitude (m, default 0.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Optional

from fastapi import FastAPI
import uvicorn

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

import sapient_msg_to_cot

import sapient_encode_decode_msg as framer


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


BIND       = os.environ.get("COT_BRIDGE_BIND", "0.0.0.0")
PORT       = int(os.environ.get("COT_BRIDGE_PORT", "5005"))
HTTP_PORT  = int(os.environ.get("COT_BRIDGE_HTTP_PORT", "8092"))
TAK_HOST   = os.environ.get("TAK_HOST", "192.168.201.222")
TAK_PORT   = int(os.environ.get("TAK_PORT", "6969"))
FB_LAT    = _env_float("FALLBACK_LAT")
FB_LON    = _env_float("FALLBACK_LON")
FB_ALT    = _env_float("FALLBACK_ALT") or 0.0


_stats = {
    "frames_in": 0,
    "cot_out": 0,
    "skipped_no_position": 0,
    "skipped_no_mapping": 0,
    "send_errors": 0,
}


def _convert_and_send(msg: _msg.SapientMessage) -> None:
    content = msg.WhichOneof("content")
    xml = sapient_msg_to_cot.convert(
        msg, fallback_lat=FB_LAT, fallback_lon=FB_LON, fallback_alt=FB_ALT,
    )
    if xml is None:
        if content in ("registration", "status_report", "detection_report", "alert"):
            _stats["skipped_no_position"] += 1
            log.info("skipped %s (no position; set FALLBACK_LAT/LON or include Location)",
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


# Tiny HTTP surface so regression tests can probe the service black-box —
# without it cot-bridge would have no observable interface except log lines
# and the outbound UDP packets (which are awkward to assert against).
api = FastAPI(title="cot-bridge")


@api.get("/health")
def health() -> dict:
    return {"ok": True}


@api.get("/stats")
def stats() -> dict:
    return {
        "bind": BIND, "port": PORT,
        "tak_host": TAK_HOST, "tak_port": TAK_PORT,
        "fallback_lat": FB_LAT, "fallback_lon": FB_LON, "fallback_alt": FB_ALT,
        **_stats,
    }


async def main() -> None:
    server = await asyncio.start_server(handle_client, BIND, PORT)
    log.info("cot-bridge listening on %s:%d (TAK target udp://%s:%d, fallback lat=%s lon=%s)",
             BIND, PORT, TAK_HOST, TAK_PORT, FB_LAT, FB_LON)
    log.info("cot-bridge HTTP /health + /stats on %s:%d", BIND, HTTP_PORT)
    http_config = uvicorn.Config(api, host=BIND, port=HTTP_PORT,
                                 log_level="warning", access_log=False)
    http_server = uvicorn.Server(http_config)
    async with server:
        await asyncio.gather(
            server.serve_forever(),
            _stats_ticker(),
            http_server.serve(),
        )


if __name__ == "__main__":
    asyncio.run(main())
