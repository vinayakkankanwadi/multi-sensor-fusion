"""Scenario implementations.

Each scenario is an `async def run(client, recorder, ctx) -> None` coroutine
registered in `REGISTRY`. The CLI looks up scenarios by name.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from driver.client import SapientTcpClient
from driver.recorder import Recorder

from scenarios import (
    alert,
    detection,
    error_recv,
    error_send,
    listen,
    registration,
    shutdown,
    status,
    task_ack,
)


@dataclass
class Context:
    node_id: str
    recv_timeout_s: float


ScenarioFn = Callable[[SapientTcpClient, Recorder, Context], Awaitable[None]]


REGISTRY: dict[str, ScenarioFn] = {
    "registration": registration.run,
    "status": status.run,
    "detection": detection.run,
    "alert": alert.run,
    "task_ack": task_ack.run,
    "error_send": error_send.run,
    "error_recv": error_recv.run,
    "listen": listen.run,
    "shutdown": shutdown.run,
}


def get(name: str) -> ScenarioFn:
    if name not in REGISTRY:
        raise KeyError(f"unknown scenario: {name}; known: {sorted(REGISTRY)}")
    return REGISTRY[name]
