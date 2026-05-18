"""Tests drawer — /api/regression/* proxied to `services/regression`."""

from __future__ import annotations

from fastapi import APIRouter

from . import client

router = APIRouter(prefix="/api/regression", tags=["tests"])


@router.get("/status")
async def status() -> dict:
    return await client.status()


@router.get("/result")
async def result() -> dict:
    return await client.result()


@router.post("/run")
async def run() -> dict:
    return await client.run()
