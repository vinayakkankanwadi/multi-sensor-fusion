"""SAPIENT BSI Flex 335 v2 → Cursor-on-Target (CoT) converter.

Registration / StatusReport / DetectionReport / Alert become CoT events;
RegistrationAck / TaskAck / AlertAck / Task / Error return None.

When a message lacks a usable position the caller can pass
`fallback_lat`/`fallback_lon`/`fallback_alt`; if neither is available
the converter returns None — callers should not push positionless events
to TAK.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from sapient_msg.bsi_flex_335_v2_0 import (
    registration_pb2 as _reg,
    sapient_message_pb2 as _msg,
)


# Registration node_type → CoT event.type (2525C). Edges are friendly.
NODE_TYPE_TO_COT = {
    _reg.Registration.NODE_TYPE_RADAR:           "a-f-G-E-S-R",
    _reg.Registration.NODE_TYPE_LIDAR:           "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_CAMERA:          "a-f-G-E-S-E",
    _reg.Registration.NODE_TYPE_SEISMIC:         "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_ACOUSTIC:        "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_PROXIMITY_SENSOR:"a-f-G-E-S",
    _reg.Registration.NODE_TYPE_PASSIVE_RF:      "a-f-G-E-S-W",
    _reg.Registration.NODE_TYPE_HUMAN:           "a-f-G-U-C-I",
    _reg.Registration.NODE_TYPE_CHEMICAL:        "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_BIOLOGICAL:      "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_RADIATION:       "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_KINETIC:         "a-f-G-E-V-A",
    _reg.Registration.NODE_TYPE_JAMMER:          "a-f-G-E-X-J",
    _reg.Registration.NODE_TYPE_CYBER:           "a-f-G-U",
    _reg.Registration.NODE_TYPE_LDEW:            "a-f-G-E-W-L",
    _reg.Registration.NODE_TYPE_RFDEW:           "a-f-G-E-W-D",
    _reg.Registration.NODE_TYPE_MOBILE_NODE:     "a-f-G-U",
    _reg.Registration.NODE_TYPE_POINTABLE_NODE:  "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_FUSION_NODE:     "a-f-G-U-H",
    _reg.Registration.NODE_TYPE_OTHER:           "a-f-G-U",
    _reg.Registration.NODE_TYPE_UNSPECIFIED:     "a-f-G-U",
}

DETECTION_DEFAULT_TYPE = "a-u-G"
ALERT_DEFAULT_TYPE     = "a-h-G"
NODE_DEFAULT_TYPE      = "a-f-G-U"


def _utc(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _build_cot(*, uid: str, cot_type: str,
               lat: float, lon: float, hae: float,
               callsign: str, remarks: str,
               stale_seconds: int) -> bytes:
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=stale_seconds)
    event = Element("event", {
        "version": "2.0", "uid": uid, "type": cot_type,
        "time":  _utc(now), "start": _utc(now), "stale": _utc(stale),
        "how":   "m-g",
    })
    SubElement(event, "point", {
        "lat": f"{lat:.7f}", "lon": f"{lon:.7f}", "hae": f"{hae:.3f}",
        "ce":  "9999999.0", "le":  "9999999.0",
    })
    detail = SubElement(event, "detail")
    SubElement(detail, "contact", {"callsign": callsign})
    SubElement(detail, "__group", {"name": "Cyan", "role": "Team Member"})
    SubElement(detail, "precisionlocation", {"altsrc": "GPS", "geopointsrc": "GPS"})
    if remarks:
        r = SubElement(detail, "remarks")
        r.text = remarks
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(event)


def _location_from(loc) -> tuple[float, float, float] | None:
    # SAPIENT v2 location.proto: x=lat, y=lon when coordinate_system is
    # LAT_LNG_DEG_M (the over-the-wire choice the ui's templates use).
    if loc is None or not loc.HasField("x") or not loc.HasField("y"):
        return None
    alt = loc.z if loc.HasField("z") else 0.0
    return loc.x, loc.y, alt


def _registration_meta(message: _msg.SapientMessage) -> tuple[str, str, str]:
    r = message.registration
    node_type = (r.node_definition[0].node_type
                 if r.node_definition else _reg.Registration.NODE_TYPE_UNSPECIFIED)
    cot_type = NODE_TYPE_TO_COT.get(node_type, NODE_DEFAULT_TYPE)
    callsign = r.short_name or r.name
    if not callsign and r.config_data:
        callsign = r.config_data[0].model
    if not callsign:
        callsign = f"node-{message.node_id[:8]}"
    remarks = (f"SAPIENT Registration · node_type="
               f"{_reg.Registration.NodeType.Name(node_type)}")
    return cot_type, callsign, remarks


# (loc_provider, uid_fn, meta_fn, stale_seconds)
#   loc_provider: returns (lat, lon, alt) from message or None
#   uid_fn:       returns CoT uid
#   meta_fn:      returns (cot_type, callsign, remarks)
_CONTENT_HANDLERS = {
    "registration": (
        lambda m: None,  # registration has no location of its own
        lambda m: m.node_id,
        _registration_meta,
        300,
    ),
    "status_report": (
        lambda m: _location_from(m.status_report.node_location)
                  if m.status_report.HasField("node_location") else None,
        lambda m: m.node_id,
        lambda m: (
            NODE_DEFAULT_TYPE,
            f"node-{m.node_id[:8]}",
            f"SAPIENT StatusReport · system="
            f"{m.status_report.System.Name(m.status_report.system)} "
            f"mode={m.status_report.mode}",
        ),
        300,
    ),
    "detection_report": (
        lambda m: _location_from(m.detection_report.location)
                  if m.detection_report.HasField("location") else None,
        lambda m: f"det-{m.detection_report.object_id or m.detection_report.report_id}",
        lambda m: (
            DETECTION_DEFAULT_TYPE,
            f"det-{(m.detection_report.object_id or m.detection_report.report_id)[:8]}",
            f"SAPIENT DetectionReport · node={m.node_id[:8]} "
            f"report={m.detection_report.report_id}",
        ),
        600,
    ),
    "alert": (
        lambda m: _location_from(m.alert.location)
                  if m.alert.HasField("location") else None,
        lambda m: f"alert-{m.alert.alert_id}",
        lambda m: (
            ALERT_DEFAULT_TYPE,
            f"alert-{m.alert.alert_id[:8]}",
            f"SAPIENT Alert · {m.alert.description or 'alert'}",
        ),
        900,
    ),
}


def convert(message: _msg.SapientMessage, *,
            fallback_lat: float | None = None,
            fallback_lon: float | None = None,
            fallback_alt: float | None = None) -> bytes | None:
    """Convert a SapientMessage to a CoT XML byte payload.

    Returns None for content kinds that don't map to a CoT marker
    (Task, TaskAck, AlertAck, RegistrationAck, Error) or when no
    position is available.
    """
    handler = _CONTENT_HANDLERS.get(message.WhichOneof("content"))
    if handler is None:
        return None
    loc_provider, uid_fn, meta_fn, stale_seconds = handler

    pos = loc_provider(message)
    if pos is None:
        if fallback_lat is None or fallback_lon is None:
            return None
        pos = (fallback_lat, fallback_lon, fallback_alt or 0.0)

    cot_type, callsign, remarks = meta_fn(message)
    return _build_cot(
        uid=uid_fn(message), cot_type=cot_type,
        lat=pos[0], lon=pos[1], hae=pos[2],
        callsign=callsign, remarks=remarks,
        stale_seconds=stale_seconds,
    )
