"""SAPIENT BSI Flex 335 v2 → Cursor-on-Target (CoT) converter.

Each SAPIENT message that has (or implies) a position becomes a CoT event:

  Registration       → marker for the edge node itself (callsign, type from node_type)
  StatusReport       → refresh of the edge-node marker (uses status_report.node_location)
  DetectionReport    → marker for the detected object  (uses detection_report.location)
  Alert              → high-priority marker            (uses alert.location)

If a message lacks a usable position, the caller can supply a `fallback_lat`/
`fallback_lon`/`fallback_alt` (e.g. the edge node's GPS reading) and the
converter will use that. If no position is available at all, the function
returns None — callers should not push positionless events to TAK.

Output is the byte payload of one CoT event, ready to UDP-send to a TAK
Server CoT input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from xml.etree.ElementTree import Element, SubElement, tostring

from sapient_msg.bsi_flex_335_v2_0 import (
    registration_pb2 as _reg,
    sapient_message_pb2 as _msg,
)


# --- 2525C / TAK type codes -------------------------------------------------
# Registration node_type → CoT event.type. Edges are friendly by default.
NODE_TYPE_TO_COT = {
    _reg.Registration.NODE_TYPE_RADAR:           "a-f-G-E-S-R",   # Friend Ground Equipment Sensor Radar
    _reg.Registration.NODE_TYPE_LIDAR:           "a-f-G-E-S",     # Sensor (no LIDAR-specific symbol)
    _reg.Registration.NODE_TYPE_CAMERA:          "a-f-G-E-S-E",   # Sensor Electro-optical
    _reg.Registration.NODE_TYPE_SEISMIC:         "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_ACOUSTIC:        "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_PROXIMITY_SENSOR:"a-f-G-E-S",
    _reg.Registration.NODE_TYPE_PASSIVE_RF:      "a-f-G-E-S-W",   # Sensor (RF Warfare)
    _reg.Registration.NODE_TYPE_HUMAN:           "a-f-G-U-C-I",   # Friend Unit Combat Infantry
    _reg.Registration.NODE_TYPE_CHEMICAL:        "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_BIOLOGICAL:      "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_RADIATION:       "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_KINETIC:         "a-f-G-E-V-A",   # Friend Equipment Vehicle Armoured
    _reg.Registration.NODE_TYPE_JAMMER:          "a-f-G-E-X-J",   # EW Jammer
    _reg.Registration.NODE_TYPE_CYBER:           "a-f-G-U",       # Generic friendly unit
    _reg.Registration.NODE_TYPE_LDEW:            "a-f-G-E-W-L",   # Weapon Laser
    _reg.Registration.NODE_TYPE_RFDEW:           "a-f-G-E-W-D",   # Weapon Directed Energy
    _reg.Registration.NODE_TYPE_MOBILE_NODE:     "a-f-G-U",
    _reg.Registration.NODE_TYPE_POINTABLE_NODE:  "a-f-G-E-S",
    _reg.Registration.NODE_TYPE_FUSION_NODE:     "a-f-G-U-H",     # Headquarters
    _reg.Registration.NODE_TYPE_OTHER:           "a-f-G-U",
    _reg.Registration.NODE_TYPE_UNSPECIFIED:     "a-f-G-U",
}

# Default for detections (unknown affiliation, ground)
DETECTION_DEFAULT_TYPE = "a-u-G"
# Alerts are typically threats — hostile until proven otherwise.
ALERT_DEFAULT_TYPE = "a-h-G"


def _utc(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _build_cot(*, uid: str, cot_type: str,
               lat: float, lon: float, hae: float,
               callsign: str, remarks: str,
               stale_seconds: int = 300,
               group_name: str = "Cyan",
               group_role: str = "Team Member") -> bytes:
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
    SubElement(detail, "__group", {"name": group_name, "role": group_role})
    SubElement(detail, "precisionlocation", {"altsrc": "GPS", "geopointsrc": "GPS"})
    if remarks:
        r = SubElement(detail, "remarks")
        r.text = remarks
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(event)


def _location_from(loc) -> tuple[float, float, float] | None:
    """Pull (lat, lon, alt) from a SAPIENT Location message if usable."""
    if loc is None:
        return None
    # Both x/y must be present; in the v2 SAPIENT location.proto, x=longitude or
    # easting depending on coordinate_system, y=latitude or northing. For this
    # converter we treat LAT_LNG_DEG_M (the most common over-the-wire choice
    # for the msf-ui's templates) as x=lat, y=lon — match what the
    # template_loader uses.
    if not loc.HasField("x") or not loc.HasField("y"):
        return None
    lat, lon = loc.x, loc.y
    alt = loc.z if loc.HasField("z") else 0.0
    return lat, lon, alt


# --- per-content converters -------------------------------------------------

def cot_for_registration(message: _msg.SapientMessage, *,
                         fallback_lat: float | None = None,
                         fallback_lon: float | None = None,
                         fallback_alt: float | None = None,
                         stale_seconds: int = 300) -> bytes | None:
    r = message.registration
    node_type = (r.node_definition[0].node_type
                 if r.node_definition else _reg.Registration.NODE_TYPE_UNSPECIFIED)
    cot_type = NODE_TYPE_TO_COT.get(node_type, "a-f-G-U")
    callsign = r.short_name or r.name
    if not callsign and r.config_data:
        callsign = r.config_data[0].model
    if not callsign:
        callsign = f"node-{message.node_id[:8]}"
    if fallback_lat is None or fallback_lon is None:
        return None
    return _build_cot(
        uid=message.node_id, cot_type=cot_type,
        lat=fallback_lat, lon=fallback_lon, hae=fallback_alt or 0.0,
        callsign=callsign,
        remarks=f"SAPIENT Registration · node_type={_reg.Registration.NodeType.Name(node_type)}",
        stale_seconds=stale_seconds,
    )


def cot_for_status_report(message: _msg.SapientMessage, *,
                          fallback_lat: float | None = None,
                          fallback_lon: float | None = None,
                          fallback_alt: float | None = None,
                          stale_seconds: int = 300) -> bytes | None:
    s = message.status_report
    pos = _location_from(s.node_location) if s.HasField("node_location") else None
    if pos is None and (fallback_lat is None or fallback_lon is None):
        return None
    lat, lon, alt = pos if pos is not None else (
        fallback_lat, fallback_lon, fallback_alt or 0.0)
    return _build_cot(
        uid=message.node_id, cot_type="a-f-G-U",
        lat=lat, lon=lon, hae=alt,
        callsign=f"node-{message.node_id[:8]}",
        remarks=f"SAPIENT StatusReport · system={s.System.Name(s.system)} mode={s.mode}",
        stale_seconds=stale_seconds,
    )


def cot_for_detection_report(message: _msg.SapientMessage, *,
                             fallback_lat: float | None = None,
                             fallback_lon: float | None = None,
                             fallback_alt: float | None = None,
                             stale_seconds: int = 600) -> bytes | None:
    d = message.detection_report
    pos = _location_from(d.location) if d.HasField("location") else None
    if pos is None and (fallback_lat is None or fallback_lon is None):
        return None
    lat, lon, alt = pos if pos is not None else (
        fallback_lat, fallback_lon, fallback_alt or 0.0)
    return _build_cot(
        uid=f"det-{d.object_id or d.report_id}",
        cot_type=DETECTION_DEFAULT_TYPE,
        lat=lat, lon=lon, hae=alt,
        callsign=f"det-{(d.object_id or d.report_id)[:8]}",
        remarks=f"SAPIENT DetectionReport · node={message.node_id[:8]} report={d.report_id}",
        stale_seconds=stale_seconds,
    )


def cot_for_alert(message: _msg.SapientMessage, *,
                  fallback_lat: float | None = None,
                  fallback_lon: float | None = None,
                  fallback_alt: float | None = None,
                  stale_seconds: int = 900) -> bytes | None:
    a = message.alert
    pos = _location_from(a.location) if a.HasField("location") else None
    if pos is None and (fallback_lat is None or fallback_lon is None):
        return None
    lat, lon, alt = pos if pos is not None else (
        fallback_lat, fallback_lon, fallback_alt or 0.0)
    return _build_cot(
        uid=f"alert-{a.alert_id}", cot_type=ALERT_DEFAULT_TYPE,
        lat=lat, lon=lon, hae=alt,
        callsign=f"alert-{a.alert_id[:8]}",
        remarks=f"SAPIENT Alert · {a.description or 'alert'}",
        stale_seconds=stale_seconds,
    )


# --- single-entry dispatcher -----------------------------------------------

def convert(message: _msg.SapientMessage, *,
            fallback_lat: float | None = None,
            fallback_lon: float | None = None,
            fallback_alt: float | None = None) -> bytes | None:
    """Convert any supported SapientMessage to a CoT XML byte payload.

    Returns None for content cases that don't map to a CoT marker (Task,
    TaskAck, AlertAck, RegistrationAck, Error) or when no position is
    available.
    """
    content = message.WhichOneof("content")
    kw = dict(fallback_lat=fallback_lat, fallback_lon=fallback_lon,
              fallback_alt=fallback_alt)
    if content == "registration":
        return cot_for_registration(message, **kw)
    if content == "status_report":
        return cot_for_status_report(message, **kw)
    if content == "detection_report":
        return cot_for_detection_report(message, **kw)
    if content == "alert":
        return cot_for_alert(message, **kw)
    return None
