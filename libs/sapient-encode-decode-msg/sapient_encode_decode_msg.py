"""Encode + decode SAPIENT messages on the wire (spec §4.2).

Every SAPIENT TCP frame is `<uint32_le payload_length><payload bytes>`,
where `payload bytes` is a serialized `SapientMessage` proto. This is the
only place in the codebase that knows that format:

    encode(payload)         -> prefix and return bytes ready to send
    read_frames(reader)     -> async generator yielding successive payloads

Used by every component that touches the SAPIENT wire (ui sends, cot-bridge
receives, any future SAPIENT producer/consumer).
"""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator

_HEADER = struct.Struct("<I")
HEADER_LEN = _HEADER.size   # 4


def encode(payload: bytes) -> bytes:
    """Prepend the 4-byte little-endian length header to a serialized message."""
    return _HEADER.pack(len(payload)) + payload


async def read_frames(reader: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Yield successive payloads from a stream until EOF."""
    while True:
        header = await reader.readexactly(HEADER_LEN)
        (length,) = _HEADER.unpack(header)
        payload = await reader.readexactly(length)
        yield payload
