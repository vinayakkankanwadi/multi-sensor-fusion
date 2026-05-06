"""SAPIENT BSI Flex 335 v2 wire framer.

Spec §4.2: each protobuf message is preceded by a 4-byte little-endian
length prefix. The prefix value is the payload length, not including
the prefix itself.
"""

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
    """Yield successive payloads from a stream until EOF.

    Each iteration reads exactly one header + payload. Raises
    `asyncio.IncompleteReadError` if the stream ends mid-frame.
    """
    while True:
        header = await reader.readexactly(HEADER_LEN)
        (length,) = _HEADER.unpack(header)
        payload = await reader.readexactly(length)
        yield payload


def split_stream(buf: bytes) -> tuple[list[bytes], bytes]:
    """Sync helper for tests/replay: split a buffered byte string into frames.

    Returns (complete_frames, remainder).
    """
    frames: list[bytes] = []
    i = 0
    n = len(buf)
    while n - i >= HEADER_LEN:
        (length,) = _HEADER.unpack_from(buf, i)
        end = i + HEADER_LEN + length
        if end > n:
            break
        frames.append(bytes(buf[i + HEADER_LEN : end]))
        i = end
    return frames, bytes(buf[i:])
