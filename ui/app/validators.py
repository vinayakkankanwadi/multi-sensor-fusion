"""Client-side SAPIENT message validators.

Mirror the Windows reference harness's FluentValidation rules
(BSI-Flex-335-v2-Test-Harness/SapientServices/Data/Validation/) so the UI
can fail-fast before sending. Used when the request's `validate_before_send`
flag is true.

These are intentionally a strict superset of the .proto's `is_mandatory`
field options because the reference harness enforces extra constraints
(e.g. icd_version must be the literal "BSI Flex 335 v2.0", StatusReport.mode
must be a non-empty string). See `reference_harness_quirks` memory.
"""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

# ULID is 26 chars, Crockford base32 (excludes I, L, O, U).
_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def _is_valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_ulid(s: str) -> bool:
    return bool(_ULID_RE.match(s or ""))


def _scalar_in_unit_interval(x: float) -> bool:
    return 0.0 <= x <= 1.0


def _err(buf: list[str], cond: bool, msg: str) -> None:
    if not cond:
        buf.append(msg)


def validate(message: _msg.SapientMessage) -> list[str]:
    """Return a list of error strings; empty if the message is valid."""
    errors: list[str] = []

    # Wrapper.
    _err(errors, message.HasField("timestamp"),
         "SapientMessage.timestamp is mandatory")
    _err(errors, bool(message.node_id) and _is_valid_uuid(message.node_id),
         "SapientMessage.node_id must be a valid UUID")
    if message.destination_id:
        _err(errors, _is_valid_uuid(message.destination_id),
             "SapientMessage.destination_id must be a valid UUID when set")

    content = message.WhichOneof("content")
    _err(errors, content is not None, "SapientMessage.content is mandatory")

    if content == "registration":
        errors.extend(_validate_registration(message.registration))
    elif content == "registration_ack":
        errors.extend(_validate_registration_ack(message.registration_ack))
    elif content == "status_report":
        errors.extend(_validate_status_report(message.status_report))
    elif content == "detection_report":
        errors.extend(_validate_detection_report(message.detection_report))
    elif content == "task":
        errors.extend(_validate_task(message.task))
    elif content == "task_ack":
        errors.extend(_validate_task_ack(message.task_ack))
    elif content == "alert":
        errors.extend(_validate_alert(message.alert))
    elif content == "alert_ack":
        errors.extend(_validate_alert_ack(message.alert_ack))
    elif content == "error":
        errors.extend(_validate_error(message.error))

    return errors


def _validate_registration(r) -> list[str]:
    errs: list[str] = []
    _err(errs, len(r.node_definition) > 0,
         "Registration.node_definition is mandatory")
    _err(errs, r.icd_version == "BSI Flex 335 v2.0",
         'Registration.icd_version must be the literal "BSI Flex 335 v2.0" (validator quirk)')
    _err(errs, len(r.capabilities) > 0,
         "Registration.capabilities is mandatory")
    _err(errs, r.HasField("status_definition"),
         "Registration.status_definition is mandatory")
    _err(errs, len(r.mode_definition) > 0,
         "Registration.mode_definition is mandatory")
    _err(errs, len(r.config_data) > 0,
         "Registration.config_data is mandatory")
    for i, md in enumerate(r.mode_definition):
        if md.HasField("task"):
            _err(errs, md.task.HasField("concurrent_tasks"),
                 f"Registration.mode_definition[{i}].task.concurrent_tasks is mandatory (validator quirk)")
    return errs


def _validate_registration_ack(ra) -> list[str]:
    errs: list[str] = []
    _err(errs, ra.HasField("acceptance"),
         "RegistrationAck.acceptance is mandatory")
    return errs


def _validate_status_report(s) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(s.report_id),
         "StatusReport.report_id is mandatory and must be a valid ULID")
    _err(errs, s.system != 0,
         "StatusReport.system is mandatory (cannot be UNSPECIFIED)")
    _err(errs, s.info != 0,
         "StatusReport.info is mandatory (cannot be UNSPECIFIED)")
    _err(errs, bool(s.mode),
         "StatusReport.mode is mandatory (validator quirk: must be non-empty)")
    if s.active_task_id:
        _err(errs, _is_valid_ulid(s.active_task_id),
             "StatusReport.active_task_id must be a valid ULID when set")
    return errs


def _validate_detection_report(d) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(d.report_id),
         "DetectionReport.report_id is mandatory and must be a valid ULID")
    _err(errs, _is_valid_ulid(d.object_id),
         "DetectionReport.object_id is mandatory and must be a valid ULID")
    if d.task_id:
        _err(errs, _is_valid_ulid(d.task_id),
             "DetectionReport.task_id must be a valid ULID when set")
    has_loc = d.HasField("location")
    has_rb = d.HasField("range_bearing")
    _err(errs, has_loc or has_rb,
         "DetectionReport must have either location or range_bearing")
    _err(errs, not (has_loc and has_rb),
         "DetectionReport must NOT have both location and range_bearing")
    if d.HasField("detection_confidence"):
        _err(errs, _scalar_in_unit_interval(d.detection_confidence),
             "DetectionReport.detection_confidence must be in [0,1]")
    return errs


def _validate_task(t) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(t.task_id),
         "Task.task_id is mandatory and must be a valid ULID")
    _err(errs, t.control != 0,
         "Task.control is mandatory (cannot be UNSPECIFIED)")
    return errs


def _validate_task_ack(ta) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(ta.task_id),
         "TaskAck.task_id is mandatory and must be a valid ULID")
    _err(errs, ta.task_status != 0,
         "TaskAck.task_status is mandatory (cannot be UNSPECIFIED)")
    return errs


def _validate_alert(a) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(a.alert_id),
         "Alert.alert_id is mandatory and must be a valid ULID")
    if a.HasField("ranking"):
        _err(errs, _scalar_in_unit_interval(a.ranking),
             "Alert.ranking must be in [0,1]")
    if a.HasField("confidence"):
        _err(errs, _scalar_in_unit_interval(a.confidence),
             "Alert.confidence must be in [0,1]")
    if a.region_id:
        _err(errs, _is_valid_ulid(a.region_id),
             "Alert.region_id must be a valid ULID when set")
    return errs


def _validate_alert_ack(aa) -> list[str]:
    errs: list[str] = []
    _err(errs, _is_valid_ulid(aa.alert_id),
         "AlertAck.alert_id is mandatory and must be a valid ULID")
    _err(errs, aa.alert_ack_status != 0,
         "AlertAck.alert_ack_status is mandatory (cannot be UNSPECIFIED)")
    return errs


def _validate_error(e) -> list[str]:
    errs: list[str] = []
    _err(errs, len(e.packet) > 0,
         "Error.packet is mandatory (must be non-empty bytes)")
    _err(errs, len(e.error_message) > 0,
         "Error.error_message is mandatory (at least one entry)")
    return errs
