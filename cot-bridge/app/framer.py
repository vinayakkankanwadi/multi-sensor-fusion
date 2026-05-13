"""SAPIENT BSI Flex 335 v2 wire framer (spec §4.2): 4-byte LE length prefix."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator

_HEADER = struct.Struct("<I")
HEADER_LEN = _HEADER.size


def encode(payload: bytes) -> bytes:
    return _HEADER.pack(len(payload)) + payload


async def read_frames(reader: asyncio.StreamReader) -> AsyncIterator[bytes]:
    while True:
        header = await reader.readexactly(HEADER_LEN)
        (length,) = _HEADER.unpack(header)
        payload = await reader.readexactly(length)
        yield payload
