"""Encode/decode tests — spec §4.2 (4-byte little-endian length prefix)."""

from __future__ import annotations

import asyncio
import struct

import pytest

import sapient_encode_decode_msg as framer


def test_encode_prepends_4_byte_le_length():
    assert framer.encode(b"hello") == struct.pack("<I", 5) + b"hello"


def test_async_read_frames_yields_each_frame():
    payloads = [b"one", b"two", b"three3333"]
    stream = b"".join(framer.encode(p) for p in payloads)

    async def collect():
        reader = asyncio.StreamReader()
        reader.feed_data(stream)
        reader.feed_eof()
        out = []
        try:
            async for frame in framer.read_frames(reader):
                out.append(frame)
        except asyncio.IncompleteReadError:
            pass
        return out

    assert asyncio.run(collect()) == payloads


def test_async_read_frames_raises_on_truncated_payload():
    payload = b"truncated"
    stream = framer.encode(payload)[:-3]

    async def collect():
        reader = asyncio.StreamReader()
        reader.feed_data(stream)
        reader.feed_eof()
        async for _ in framer.read_frames(reader):
            pass

    with pytest.raises(asyncio.IncompleteReadError):
        asyncio.run(collect())
