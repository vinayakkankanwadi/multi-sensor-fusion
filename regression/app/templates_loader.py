"""Template discovery and placeholder substitution.

A template is a JSON file under /app/templates/ representing a SapientMessage
(google.protobuf.json_format encoding). Templates may include placeholders:

    {{NOW}}      → current UTC timestamp in RFC3339, e.g. 2026-05-03T12:34:56.000Z
    {{ULID}}     → a freshly generated ULID (each occurrence is independent)
    {{NODE_ID}}  → the node UUID configured by the UI
    {{GPS_LAT}}  → latitude  in decimal degrees (live from the router GPS)
    {{GPS_LON}}  → longitude in decimal degrees
    {{GPS_ALT}}  → altitude in metres (or 0.0 if not reported)

GPS placeholders fall back to 0.0 if the router credentials aren't set or
the router has no fix yet. The substitute call is non-blocking — GPS values
are cached for ~2 seconds to avoid hitting the router on every send.

Templates pass through `_substitute(template_text, ctx)` before being parsed
into a SapientMessage protobuf. Adding a new template means dropping a JSON
file into the templates/ directory — no code changes required.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ulid
from google.protobuf import json_format

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

TEMPLATES_DIR = Path("/app/templates")

_PLACEHOLDER_RE = re.compile(r"\{\{(NOW|ULID|NODE_ID|GPS_LAT|GPS_LON|GPS_ALT)\}\}")

# Cached most-recent GPS fix to avoid hammering the router on every render.
_GPS_CACHE: dict = {"t": 0.0, "fix": None}
_GPS_CACHE_TTL_S = 2.0


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


def _gps_values() -> tuple[float, float, float]:
    """Return (lat, lon, alt) from the live NMEA fix; (0,0,0) if no fix."""
    from . import gps as _gps
    f = _gps.current_fix()
    if not f.ok:
        return 0.0, 0.0, 0.0
    return (f.latitude or 0.0, f.longitude or 0.0, f.altitude or 0.0)


def _substitute(text: str, *, node_id: str) -> str:
    """Replace placeholders with concrete values. Each {{ULID}} is unique."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    gps_evaluated = False
    lat = lon = alt = 0.0

    def repl(match: re.Match) -> str:
        nonlocal gps_evaluated, lat, lon, alt
        kind = match.group(1)
        if kind == "NOW":
            return now
        if kind == "ULID":
            return str(ulid.ULID())
        if kind == "NODE_ID":
            return node_id
        if kind in ("GPS_LAT", "GPS_LON", "GPS_ALT"):
            if not gps_evaluated:
                lat, lon, alt = _gps_values()
                gps_evaluated = True
            return {"GPS_LAT": f"{lat:.7f}",
                    "GPS_LON": f"{lon:.7f}",
                    "GPS_ALT": f"{alt:.3f}"}[kind]
        return match.group(0)

    return _PLACEHOLDER_RE.sub(repl, text)


def render(template_text: str, *, node_id: str) -> _msg.SapientMessage:
    """Substitute placeholders, then parse JSON into a SapientMessage."""
    if not _is_valid_uuid(node_id):
        raise ValueError(f"node_id is not a valid UUID: {node_id!r}")
    text = _substitute(template_text, node_id=node_id)
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
