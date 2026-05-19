"""Template discovery and placeholder substitution.

A template is a JSON file under /app/data/templates/ representing a SapientMessage
(google.protobuf.json_format encoding). Templates may include placeholders:

    {{NOW}}      → current UTC timestamp in RFC3339, e.g. 2026-05-03T12:34:56.000Z
    {{ULID}}     → a freshly generated ULID (each occurrence is independent)
    {{NODE_ID}}  → the node UUID configured by the UI
    {{GPS_LAT}}  → latitude  in decimal degrees
    {{GPS_LON}}  → longitude
    {{GPS_ALT}}  → altitude in metres

GPS values are fetched on demand from the gps service (one HTTP call per
render, only when the template actually uses a {{GPS_*}} placeholder).
If the service is unreachable or has no fix, the Brisbane fallback below
is used so messages still render with plausible coordinates.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ulid
from google.protobuf import json_format

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

TEMPLATES_DIR = Path("/app/data/templates")

_PLACEHOLDER_RE = re.compile(r"\{\{(NOW|ULID|NODE_ID|GPS_LAT|GPS_LON|GPS_ALT)\}\}")
_GPS_RE = re.compile(r"\{\{GPS_(LAT|LON|ALT)\}\}")

# Brisbane CBD fallback — used when the gps service is unreachable or
# reports no current fix. Keeps templates renderable on bench setups
# with no GPS hardware.
_FALLBACK_LAT = -27.4705
_FALLBACK_LON = 153.0260
_FALLBACK_ALT = 28.0

_GPS_TIMEOUT_S = 1.5


def list_templates() -> list[dict]:
    """Discover .json templates and return name + raw text + decoded preview."""
    out = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        text = path.read_text()
        try:
            preview = json.loads(text)
        except json.JSONDecodeError as exc:
            preview = {"_parse_error": str(exc)}
        out.append({
            "name": path.stem,
            "filename": path.name,
            "raw": text,
            "preview": preview,
        })
    return out


def get_template(name: str) -> str:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"template not found: {name}")
    return path.read_text()


def _fetch_gps_sync() -> dict | None:
    url = os.environ.get("GPS_URL", "http://127.0.0.1:8090").rstrip("/")
    req = urllib.request.Request(f"{url}/gps/current",
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_GPS_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


async def _resolve_gps() -> tuple[float, float, float]:
    fix = await asyncio.to_thread(_fetch_gps_sync)
    if fix and fix.get("ok"):
        return (
            float(fix.get("latitude")  or _FALLBACK_LAT),
            float(fix.get("longitude") or _FALLBACK_LON),
            float(fix.get("altitude")  or _FALLBACK_ALT),
        )
    return (_FALLBACK_LAT, _FALLBACK_LON, _FALLBACK_ALT)


def _substitute(text: str, *, node_id: str,
                gps: tuple[float, float, float]) -> str:
    """Replace placeholders with concrete values. Each {{ULID}} is unique."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    lat, lon, alt = gps

    def repl(match: re.Match) -> str:
        kind = match.group(1)
        if kind == "NOW":     return now
        if kind == "ULID":    return str(ulid.ULID())
        if kind == "NODE_ID": return node_id
        if kind == "GPS_LAT": return f"{lat:.7f}"
        if kind == "GPS_LON": return f"{lon:.7f}"
        if kind == "GPS_ALT": return f"{alt:.3f}"
        return match.group(0)

    return _PLACEHOLDER_RE.sub(repl, text)


async def render(template_text: str, *,
                 node_id: str) -> _msg.SapientMessage:
    """Substitute placeholders, then parse JSON into a SapientMessage.

    GPS is fetched live from the gps service only if the template uses
    {{GPS_*}}; falls back to Brisbane CBD if the service has no fix.
    """
    if not _is_valid_uuid(node_id):
        raise ValueError(f"node_id is not a valid UUID: {node_id!r}")
    gps = await _resolve_gps() if _GPS_RE.search(template_text) \
        else (_FALLBACK_LAT, _FALLBACK_LON, _FALLBACK_ALT)
    text = _substitute(template_text, node_id=node_id, gps=gps)
    msg = _msg.SapientMessage()
    json_format.Parse(text, msg, ignore_unknown_fields=False)
    return msg


def message_to_dict(msg: _msg.SapientMessage) -> dict:
    """Decode a SapientMessage into a dict for transcript display."""
    return json_format.MessageToDict(msg, preserving_proto_field_name=True)


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, TypeError):
        return False
