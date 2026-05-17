"""Converter tests: every content case round-trips and validates."""

from __future__ import annotations

from google.protobuf import json_format

from app import proto_to_template, validators
from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg


def _hydrate_placeholders(text: str) -> str:
    return (
        text.replace("{{NOW}}", "2026-05-03T12:00:00Z")
            .replace("{{NODE_ID}}", "11111111-1111-1111-1111-111111111111")
            .replace("{{ULID}}", "01HABCDEFGHJKMNPQRSTVWXYZ0")
    )


def test_lists_all_nine_content_cases():
    assert set(proto_to_template.list_content_cases()) == {
        "registration", "registration_ack", "status_report", "detection_report",
        "task", "task_ack", "alert", "alert_ack", "error",
    }


def test_each_template_parses_back_to_protobuf():
    for case in proto_to_template.list_content_cases():
        text = proto_to_template.build_template_for_content(case)
        msg = _msg.SapientMessage()
        json_format.Parse(_hydrate_placeholders(text), msg)
        assert msg.WhichOneof("content") == case


def test_each_template_passes_client_validator():
    for case in proto_to_template.list_content_cases():
        text = proto_to_template.build_template_for_content(case)
        msg = _msg.SapientMessage()
        json_format.Parse(_hydrate_placeholders(text), msg)
        errs = validators.validate(msg)
        assert errs == [], f"{case}: {errs}"


def test_registration_quirks_present():
    text = proto_to_template.build_template_for_content("registration")
    msg = _msg.SapientMessage()
    json_format.Parse(_hydrate_placeholders(text), msg)
    assert msg.registration.icd_version == "BSI Flex 335 v2.0"
    assert msg.registration.mode_definition[0].task.HasField("concurrent_tasks")


def test_duration_value_is_non_zero():
    """value=0.0 round-trips through MessageToJson as 'absent' and the
    DurationValidator on the Windows side rejects it."""
    text = proto_to_template.build_template_for_content("registration")
    msg = _msg.SapientMessage()
    json_format.Parse(_hydrate_placeholders(text), msg)
    assert msg.registration.status_definition.status_interval.value > 0
    for md in msg.registration.mode_definition:
        assert md.settle_time.value > 0


def test_status_report_quirk_present():
    text = proto_to_template.build_template_for_content("status_report")
    msg = _msg.SapientMessage()
    json_format.Parse(_hydrate_placeholders(text), msg)
    assert msg.status_report.mode != ""


def test_placeholders_substituted_for_id_fields():
    for case in proto_to_template.list_content_cases():
        text = proto_to_template.build_template_for_content(case)
        # Top-level node_id and timestamp always substituted.
        assert "{{NODE_ID}}" in text
        assert "{{NOW}}" in text
