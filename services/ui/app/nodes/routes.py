"""Nodes drawer — /api/nodes CRUD proxied through to `services/nodes`."""

from __future__ import annotations

import json
import urllib.error

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import client

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


class NodeCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    host: str = Field(..., min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    admin_port: int | None = Field(None, ge=1, le=65535)
    protocol: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


class NodePatch(BaseModel):
    # Same field set the nodes service expects — id/type immutable.
    name: str | None = Field(None, min_length=1, max_length=128)
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    services: list[str] | None = None
    kind: str | None = Field(None, max_length=64)
    probe: bool | None = None
    health_path: str | None = Field(None, max_length=128)
    probe_kind: str | None = Field(None, max_length=16)
    admin_port: int | None = Field(None, ge=1, le=65535)
    protocol: str | None = Field(None, max_length=16)
    description: str | None = Field(None, max_length=4096)


def _proxy_error(exc: Exception) -> HTTPException:
    """Map urllib HTTPErrors back to the right status + detail. Anything
    else becomes a 502 (the nodes service errored, we're a proxy)."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8")
            detail = json.loads(body).get("detail", body) if body else exc.reason
        except Exception:
            detail = str(exc)
        return HTTPException(status_code=exc.code, detail=detail)
    return HTTPException(status_code=502, detail=f"nodes service: {exc}")


@router.get("")
async def list_nodes(type: str | None = None) -> dict:
    """Unified registry + status for every named platform resource. `?type=…`
    filters to a subset (platform-node, middleware, service, tak-server)."""
    return await client.fetch_current(type=type)


@router.post("", status_code=201)
async def create_node(req: NodeCreate) -> dict:
    try:
        return await client.create(req.model_dump(exclude_none=True))
    except Exception as exc:
        raise _proxy_error(exc)


@router.patch("/{node_id}")
async def patch_node(node_id: str, req: NodePatch) -> dict:
    body = req.model_dump(exclude_none=True)
    if not body:
        raise HTTPException(status_code=400,
                            detail="provide at least one field to update")
    try:
        return await client.patch_one(node_id, body)
    except Exception as exc:
        raise _proxy_error(exc)


@router.delete("/{node_id}")
async def delete_node(node_id: str) -> dict:
    try:
        return await client.delete(node_id)
    except Exception as exc:
        raise _proxy_error(exc)
