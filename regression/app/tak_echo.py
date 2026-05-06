"""TAK Server echo listener.

When TAK Server is configured with a `<static>` subscription that mirrors
every ingested CoT to this host on UDP (e.g. address="192.168.201.107"
port="6970"), we can listen for our own messages to come back and treat
that as proof TAK accepted the CoT.

This module:
  - Binds the configured UDP port at FastAPI startup.
  - Keeps a small rolling buffer keyed by CoT `uid`.
  - Exposes `await_echo(uid, timeout)` that returns the time-since-publish
    when (and if) the UID appears in the buffer.

Caveats:
  - Requires TAK to redistribute via unicast to MSF_TAK_ECHO_PORT (Wi-Fi
    drops multicast). See README for the CoreConfig snippet.
  - If TAK isn't echoing, await_echo simply times out — the operator sees
    "TAK echo: timeout (Ns)" rather than a hard error.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_PORT = 6970
DEFAULT_BIND = "0.0.0.0"
BUFFER_SIZE = 100              # most-recent UIDs we remember
DEFAULT_AWAIT_TIMEOUT_S = 4.0  # how long we wait for an echo before giving up

_UID_RE = re.compile(rb'uid="([^"]+)"')


@dataclass
class EchoEntry:
    uid: str
    received_at: float           # time.monotonic()
    bytes_len: int
    from_addr: str
    cot_type: str | None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, listener: "TakEchoListener") -> None:
        self.listener = listener

    def datagram_received(self, data: bytes, addr) -> None:
        m = _UID_RE.search(data)
        if not m:
            return
        uid = m.group(1).decode("ascii", errors="replace")
        type_match = re.search(rb'type="([^"]+)"', data)
        cot_type = type_match.group(1).decode("ascii", errors="replace") if type_match else None
        entry = EchoEntry(
            uid=uid, received_at=time.monotonic(),
            bytes_len=len(data), from_addr=f"{addr[0]}:{addr[1]}",
            cot_type=cot_type,
        )
        self.listener._record(entry)


class TakEchoListener:
    def __init__(self, port: int = DEFAULT_PORT, bind: str = DEFAULT_BIND) -> None:
        self.port = port
        self.bind = bind
        self._buffer: list[EchoEntry] = []
        self._waiters: dict[str, asyncio.Event] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._datagrams_total: int = 0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _Protocol(self), local_addr=(self.bind, self.port))
            log.info("TAK echo listener bound to %s:%d", self.bind, self.port)
        except OSError as exc:
            log.warning("TAK echo listener could not bind %s:%d (%s) — echoes disabled",
                        self.bind, self.port, exc)
            self._transport = None

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    def _record(self, entry: EchoEntry) -> None:
        self._datagrams_total += 1
        self._buffer.append(entry)
        if len(self._buffer) > BUFFER_SIZE:
            self._buffer.pop(0)
        ev = self._waiters.get(entry.uid)
        if ev is not None:
            ev.set()

    async def await_echo(self, uid: str, *,
                         timeout: float = DEFAULT_AWAIT_TIMEOUT_S,
                         publish_time: float | None = None) -> dict:
        """Wait up to `timeout` for a CoT with matching UID to arrive.

        publish_time is `time.monotonic()` at send time; the returned
        echo_age_ms is referenced from there. If the UID is already in the
        buffer, returns immediately.
        """
        if self._transport is None:
            return {"matched": False, "reason": "echo listener not bound (port in use?)",
                    "bound": f"{self.bind}:{self.port}"}

        # Check buffer first.
        existing = next((e for e in reversed(self._buffer) if e.uid == uid), None)
        if existing is not None:
            age_ms = round((time.monotonic() - (publish_time or existing.received_at)) * 1000.0, 1)
            return {"matched": True, "echo_age_ms": age_ms,
                    "from": existing.from_addr, "bytes": existing.bytes_len,
                    "cot_type": existing.cot_type}

        ev = self._waiters.setdefault(uid, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._waiters.pop(uid, None)
            return {"matched": False,
                    "reason": f"timeout after {timeout:.1f}s (TAK didn't echo this UID)"}
        finally:
            self._waiters.pop(uid, None)

        match = next((e for e in reversed(self._buffer) if e.uid == uid), None)
        if not match:
            return {"matched": False, "reason": "internal: event set but no buffer entry"}
        age_ms = round((time.monotonic() - (publish_time or match.received_at)) * 1000.0, 1)
        return {"matched": True, "echo_age_ms": age_ms,
                "from": match.from_addr, "bytes": match.bytes_len,
                "cot_type": match.cot_type}

    def stats(self) -> dict:
        return {
            "bound": f"{self.bind}:{self.port}" if self._transport else "(not bound)",
            "datagrams_total": self._datagrams_total,
            "buffer_size": len(self._buffer),
            "recent": [
                {"uid": e.uid, "age_s": round(time.monotonic() - e.received_at, 2),
                 "from": e.from_addr, "bytes": e.bytes_len, "cot_type": e.cot_type}
                for e in list(self._buffer)[-20:]
            ],
        }


# Module-level singleton; started by the FastAPI lifespan.
listener: TakEchoListener | None = None


async def start_listener() -> None:
    global listener
    port = int(os.environ.get("MSF_TAK_ECHO_PORT", str(DEFAULT_PORT)))
    bind = os.environ.get("MSF_TAK_ECHO_BIND", DEFAULT_BIND)
    listener = TakEchoListener(port=port, bind=bind)
    await listener.start()


async def stop_listener() -> None:
    if listener:
        await listener.stop()
