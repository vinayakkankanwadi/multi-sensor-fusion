"""Validator tests: every validator must catch its known mandatory-field
violations."""

from __future__ import annotations

import pytest
from google.protobuf import timestamp_pb2 as _ts

from app import validators
from sapient_msg.bsi_flex_335_v2_0 import (
    registration_pb2 as _reg,
    sapient_message_pb2 as _msg,
)


NODE = "11111111-1111-1111-1111-111111111111"
ULID = "01HABCDEFGHJKMNPQRSTVWXYZ0"


def _envelope() -> _msg.SapientMessage:
    m = _msg.SapientMessage()
    m.timestamp.CopyFrom(_ts.Timestamp(seconds=0, nanos=0))
    m.node_id = NODE
    return m


def test_wrapper_rejects_missing_node_id():
    m = _envelope(); m.node_id = ""
    m.registration.icd_version = "BSI Flex 335 v2.0"
    errs = validators.validate(m)
    assert any("node_id" in e for e in errs)


def test_wrapper_rejects_invalid_uuid():
    m = _envelope(); m.node_id = "not-a-uuid"
    errs = validators.validate(m)
    assert any("UUID" in e for e in errs)


def test_wrapper_rejects_no_content():
    m = _envelope()
    errs = validators.validate(m)
    assert any("content" in e for e in errs)


def test_registration_rejects_wrong_icd_version():
    m = _envelope()
    m.registration.icd_version = "BSI_Flex_335_v2.0"  # underscores, the .proto value
    nd = m.registration.node_definition.add(); nd.node_type = _reg.Registration.NODE_TYPE_RADAR
    cap = m.registration.capabilities.add(); cap.category = "x"; cap.type = "y"
    sd = m.registration.status_definition.status_interval
    sd.units = _reg.Registration.TIME_UNITS_SECONDS; sd.value = 1.0
    md = m.registration.mode_definition.add()
    md.mode_name = "x"; md.mode_type = _reg.Registration.MODE_TYPE_DEFAULT
    md.task.concurrent_tasks = 1
    cd = m.registration.config_data.add(); cd.manufacturer = "x"; cd.model = "y"
    errs = validators.validate(m)
    assert any("BSI Flex 335 v2.0" in e for e in errs)


def test_status_report_rejects_empty_mode():
    m = _envelope()
    s = m.status_report
    s.report_id = ULID; s.system = 1; s.info = 1
    # mode left empty
    errs = validators.validate(m)
    assert any("mode" in e for e in errs)


def test_status_report_rejects_invalid_ulid():
    m = _envelope()
    s = m.status_report
    s.report_id = "not-a-ulid"; s.system = 1; s.info = 1; s.mode = "x"
    errs = validators.validate(m)
    assert any("ULID" in e for e in errs)


def test_detection_report_rejects_no_location():
    m = _envelope()
    d = m.detection_report
    d.report_id = ULID; d.object_id = ULID
    errs = validators.validate(m)
    assert any("location or range_bearing" in e for e in errs)


def test_alert_rejects_out_of_range_ranking():
    m = _envelope()
    m.alert.alert_id = ULID
    m.alert.ranking = 1.5  # invalid
    errs = validators.validate(m)
    assert any("ranking" in e for e in errs)


def test_error_rejects_empty_packet_or_messages():
    m = _envelope()
    m.error.error_message.append("x")
    # packet left empty
    errs = validators.validate(m)
    assert any("packet" in e for e in errs)


def test_task_rejects_unspecified_control():
    m = _envelope()
    m.task.task_id = ULID  # control left at UNSPECIFIED (0)
    errs = validators.validate(m)
    assert any("control" in e for e in errs)


def test_task_ack_rejects_unspecified_status():
    m = _envelope()
    m.task_ack.task_id = ULID
    errs = validators.validate(m)
    assert any("task_status" in e for e in errs)
