"""SAPIENT BSI Flex 335 v2 length-prefix framer (spec §4.2)."""

from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator

_HEADER = struct.Struct("<I")
HEADER_LEN = _HEADER.size  # 4


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
