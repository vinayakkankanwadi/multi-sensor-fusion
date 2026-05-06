"""Framer tests — these run without a Windows host."""

from __future__ import annotations

import asyncio
import struct

import pytest

from driver import builders, framer


def test_encode_prepends_4_byte_le_length():
    encoded = framer.encode(b"hello")
    assert len(encoded) == 9
    assert encoded[:4] == struct.pack("<I", 5)
    assert encoded[4:] == b"hello"


def test_split_stream_clean_concatenation():
    payloads = [b"a" * 1, b"b" * 200, b"c" * 65537]
    buf = b"".join(framer.encode(p) for p in payloads)
    frames, rem = framer.split_stream(buf)
    assert frames == payloads
    assert rem == b""


def test_split_stream_partial_tail():
    payload = b"x" * 50
    full = framer.encode(payload)
    # truncate by 5 bytes inside the payload
    frames, rem = framer.split_stream(full[:-5])
    assert frames == []
    assert rem == full[:-5]


def test_split_stream_partial_header():
    frames, rem = framer.split_stream(b"\x05\x00")
    assert frames == []
    assert rem == b"\x05\x00"


def test_roundtrip_real_sapient_messages():
    node = "11111111-1111-1111-1111-111111111111"
    msgs = [
        builders.registration(node).SerializeToString(),
        builders.status_report(node).SerializeToString(),
        builders.detection_report(node, x=1.0, y=2.0, z=3.0).SerializeToString(),
    ]
    stream = b"".join(framer.encode(m) for m in msgs)
    frames, rem = framer.split_stream(stream)
    assert rem == b""
    assert frames == msgs


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
    stream = framer.encode(payload)[:-3]  # cut off last 3 bytes of payload

    async def collect():
        reader = asyncio.StreamReader()
        reader.feed_data(stream)
        reader.feed_eof()
        async for _ in framer.read_frames(reader):
            pass

    with pytest.raises(asyncio.IncompleteReadError):
        asyncio.run(collect())
