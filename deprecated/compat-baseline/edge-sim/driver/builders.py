"""Builders for minimum-but-validator-passing SapientMessage payloads.

These are tuned to the Windows reference harness's FluentValidation rules
(see BSI-Flex-335-v2-Test-Harness/SapientServices/Data/Validation/*) — when
the proto and the validator disagree, the validator wins.
"""

from __future__ import annotations

from datetime import datetime, timezone

import ulid
from google.protobuf import timestamp_pb2 as _ts

from sapient_msg.bsi_flex_335_v2_0 import (
    alert_ack_pb2 as _aa,
    alert_pb2 as _alert,
    detection_report_pb2 as _det,
    error_pb2 as _err,
    location_pb2 as _loc,
    range_bearing_pb2 as _rb,
    registration_pb2 as _reg,
    sapient_message_pb2 as _msg,
    status_report_pb2 as _stat,
    task_ack_pb2 as _ta,
    task_pb2 as _task,
)


# Reference RegistrationValidator requires this exact literal — the .proto's
# standard_version option uses underscores; the validator wants spaces.
ICD_VERSION = "BSI Flex 335 v2.0"


def _now_ts() -> _ts.Timestamp:
    t = _ts.Timestamp()
    t.FromDatetime(datetime.now(timezone.utc))
    return t


def envelope(node_id: str) -> _msg.SapientMessage:
    """Wrapper with mandatory timestamp + node_id; caller fills in `content`."""
    m = _msg.SapientMessage()
    m.timestamp.CopyFrom(_now_ts())
    m.node_id = node_id
    return m


def registration(
    node_id: str,
    *,
    node_type: int = _reg.Registration.NODE_TYPE_RADAR,
    icd_version: str = ICD_VERSION,
) -> _msg.SapientMessage:
    """Build a Registration that passes RegistrationValidator + nested validators."""
    m = envelope(node_id)
    r = m.registration

    nd = r.node_definition.add()
    nd.node_type = node_type

    r.icd_version = icd_version

    cap = r.capabilities.add()
    cap.category = "General"
    cap.type = "Test"
    cap.value = "1"
    cap.units = "n/a"

    sd = r.status_definition
    sd.status_interval.units = _reg.Registration.TIME_UNITS_SECONDS
    sd.status_interval.value = 5.0

    md = r.mode_definition.add()
    md.mode_name = "default"
    md.mode_type = _reg.Registration.MODE_TYPE_DEFAULT
    md.settle_time.units = _reg.Registration.TIME_UNITS_SECONDS
    md.settle_time.value = 0.1
    md.task.concurrent_tasks = 1  # required by TaskDefinitionValidator
    region = md.task.region_definition
    region.region_type.append(_reg.Registration.REGION_TYPE_AREA_OF_INTEREST)
    region_area = region.region_area.add()
    region_area.location_units = 1
    region_area.location_datum = 1

    cd = r.config_data.add()
    cd.manufacturer = "compat-baseline"
    cd.model = "driver"

    return m


def status_report(
    node_id: str,
    *,
    system: int = _stat.StatusReport.SYSTEM_OK,
    info: int = _stat.StatusReport.INFO_NEW,
    mode: str = "default",
) -> _msg.SapientMessage:
    """Build a StatusReport that passes StatusReportValidator.

    StatusReportValidator requires report_id (ULID), system, info, and a
    non-empty mode string.
    """
    m = envelope(node_id)
    s = m.status_report
    s.report_id = str(ulid.ULID())
    s.system = system
    s.info = info
    s.mode = mode
    return m


def detection_report(
    node_id: str,
    *,
    object_id: str | None = None,
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
) -> _msg.SapientMessage:
    """Build a DetectionReport that passes DetectionReportValidator.

    Requires report_id (ULID), object_id (ULID), and a valid Location or
    RangeBearing (LocationValidator wants HasX, HasY, CoordinateSystem,
    Datum all set).
    """
    m = envelope(node_id)
    d = m.detection_report
    d.report_id = str(ulid.ULID())
    d.object_id = object_id or str(ulid.ULID())
    d.location.x = x
    d.location.y = y
    d.location.z = z
    d.location.coordinate_system = _loc.LocationCoordinateSystem.LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M
    d.location.datum = _loc.LocationDatum.LOCATION_DATUM_WGS84_E
    return m


def alert(
    node_id: str,
    *,
    alert_id: str | None = None,
    alert_type: int = _alert.Alert.ALERT_TYPE_INFORMATION,
    status: int = _alert.Alert.ALERT_STATUS_ACTIVE,
    priority: int = _alert.Alert.DISCRETE_PRIORITY_MEDIUM,
    description: str = "compat-baseline alert",
    ranking: float = 0.5,
    confidence: float = 0.9,
    with_location: bool = True,
) -> _msg.SapientMessage:
    """Build an Alert that passes AlertValidator.

    Mandatory: alert_id (ULID). Ranking and confidence must be in [0,1] if set.
    Location, if present, must satisfy LocationValidator.
    """
    m = envelope(node_id)
    a = m.alert
    a.alert_id = alert_id or str(ulid.ULID())
    a.alert_type = alert_type
    a.status = status
    a.priority = priority
    a.description = description
    a.ranking = ranking
    a.confidence = confidence
    if with_location:
        a.location.x = 0.0
        a.location.y = 0.0
        a.location.z = 0.0
        a.location.coordinate_system = _loc.LocationCoordinateSystem.LOCATION_COORDINATE_SYSTEM_LAT_LNG_DEG_M
        a.location.datum = _loc.LocationDatum.LOCATION_DATUM_WGS84_E
    return m


def alert_ack(
    node_id: str,
    *,
    alert_id: str,
    status: int = _aa.AlertAck.ALERT_ACK_STATUS_ACCEPTED,
) -> _msg.SapientMessage:
    """Build an AlertAck. Mandatory: alert_id (ULID), alert_ack_status."""
    m = envelope(node_id)
    a = m.alert_ack
    a.alert_id = alert_id
    a.alert_ack_status = status
    return m


def task_ack(
    node_id: str,
    *,
    task_id: str | None = None,
    status: int = _ta.TaskAck.TASK_STATUS_ACCEPTED,
) -> _msg.SapientMessage:
    """Build a TaskAck. Mandatory: task_id (ULID), task_status."""
    m = envelope(node_id)
    t = m.task_ack
    t.task_id = task_id or str(ulid.ULID())
    t.task_status = status
    return m


def error(
    node_id: str,
    *,
    bad_packet: bytes,
    messages: list[str],
) -> _msg.SapientMessage:
    """Build an Error. Mandatory: packet (non-empty bytes), error_message (>=1)."""
    m = envelope(node_id)
    e = m.error
    e.packet = bad_packet
    for msg_text in messages:
        e.error_message.append(msg_text)
    return m
