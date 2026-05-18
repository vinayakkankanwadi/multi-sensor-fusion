"""Template discovery and placeholder substitution.

A template is a JSON file under /app/templates/ representing a SapientMessage
(google.protobuf.json_format encoding). Templates may include placeholders:

    {{NOW}}      → current UTC timestamp in RFC3339, e.g. 2026-05-03T12:34:56.000Z
    {{ULID}}     → a freshly generated ULID (each occurrence is independent)
    {{NODE_ID}}  → the node UUID configured by the UI
    {{GPS_LAT}}  → latitude  in decimal degrees (from gps_fix, or 0.0 if None)
    {{GPS_LON}}  → longitude
    {{GPS_ALT}}  → altitude in metres

GPS placeholders fall back to 0.0 when no fix is supplied. Callers that need
live GPS pass the fix in: send / flow handlers fetch /gps/current from the
gps service once per request and hand the dict to `render()`.
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


def _substitute(text: str, *, node_id: str,
                gps_fix: dict | None) -> str:
    """Replace placeholders with concrete values. Each {{ULID}} is unique."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if gps_fix and gps_fix.get("ok"):
        lat = float(gps_fix.get("latitude")  or 0.0)
        lon = float(gps_fix.get("longitude") or 0.0)
        alt = float(gps_fix.get("altitude")  or 0.0)
    else:
        lat = lon = alt = 0.0

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


def render(template_text: str, *,
           node_id: str,
           gps_fix: dict | None = None) -> _msg.SapientMessage:
    """Substitute placeholders, then parse JSON into a SapientMessage.

    `gps_fix` is the dict returned by the gps service's /gps/current.
    Pass None for callers that don't need live coordinates (e.g. /api/validate).
    """
    if not _is_valid_uuid(node_id):
        raise ValueError(f"node_id is not a valid UUID: {node_id!r}")
    text = _substitute(template_text, node_id=node_id, gps_fix=gps_fix)
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
