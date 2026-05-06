"""Recording asyncio TCP client for SAPIENT BSI Flex 335 v2.

Connects to a host:port, frames outbound messages with the spec's 4-byte
little-endian length prefix, and parses inbound frames the same way. A
background reader task drains every inbound payload into a queue and into
the recorder, so messages are captured even when the scenario isn't
actively waiting for them (e.g. validation Errors sent unprompted by the
harness).
"""

from __future__ import annotations

import asyncio
import logging

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

from . import framer
from .recorder import Recorder

log = logging.getLogger(__name__)


class SapientTcpClient:
    def __init__(self, host: str, port: int, recorder: Recorder) -> None:
        self.host = host
        self.port = port
        self.recorder = recorder
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._inbox: asyncio.Queue[_msg.SapientMessage] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._closed = asyncio.Event()

    async def connect(self, timeout: float = 5.0) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=timeout
        )
        self._reader_task = asyncio.create_task(self._drain_inbound())

    async def _drain_inbound(self) -> None:
        assert self._reader is not None
        try:
            async for payload in framer.read_frames(self._reader):
                self.recorder.record_recv(payload)
                msg = _msg.SapientMessage()
                try:
                    msg.ParseFromString(payload)
                    await self._inbox.put(msg)
                except Exception as exc:
                    log.warning("inbound parse failed: %s", exc)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("reader task crashed")
        finally:
            self._closed.set()

    async def send(self, message: _msg.SapientMessage) -> None:
        assert self._writer is not None, "call connect() first"
        payload = message.SerializeToString()
        self.recorder.record_sent(payload)
        self._writer.write(framer.encode(payload))
        await self._writer.drain()

    async def recv(self, timeout: float = 10.0) -> _msg.SapientMessage:
        """Wait for the next inbound SapientMessage."""
        return await asyncio.wait_for(self._inbox.get(), timeout=timeout)

    async def expect(self, content_case: str, timeout: float = 10.0) -> _msg.SapientMessage:
        """Wait for the next inbound message of a specific content case.

        Skips and logs other inbound messages encountered while waiting
        (they were still recorded by the background reader).
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"timed out waiting for {content_case}")
            msg = await self.recv(timeout=remaining)
            got = msg.WhichOneof("content")
            if got == content_case:
                return msg
            log.info("skipping unrelated inbound %s while waiting for %s",
                     got, content_case)

    async def drain_for(self, seconds: float) -> None:
        """Block for `seconds`, letting the background reader keep recording."""
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
