"""Convert .proto descriptors → JSON templates for every SapientMessage
content oneof case.

Runs at build time (and on demand via `POST /api/regenerate-templates` or
the `regenerate_templates` CLI). Eliminates hand-written templates so any
.proto change can be picked up by re-running the converter.

Recipe for each `oneof content` case:

  1. Build a default `SapientMessage` with that content set.
  2. Recursively populate every field declared mandatory (`is_mandatory`
     in `proto_options.proto`), every nested mandatory oneof, plus the
     known-required-but-unflagged fields the Windows reference validator
     enforces (Registration.icd_version literal, StatusReport.mode,
     TaskDefinition.concurrent_tasks).
  3. Set ULID fields to `{{ULID}}`, top-level `node_id` to `{{NODE_ID}}`,
     and post-process the JSON to use `{{NOW}}` for the wrapper timestamp.
  4. Serialise via `google.protobuf.json_format.MessageToJson`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from google.protobuf import json_format
from google.protobuf.descriptor import FieldDescriptor

from sapient_msg import proto_options_pb2 as _opts
from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2 as _msg

log = logging.getLogger(__name__)

DEFAULT_TEMPLATES_DIR = Path("/app/templates")
PLACEHOLDER_NODE_ID = "00000000-0000-0000-0000-000000000000"

# Fields the reference Windows validator requires that are not marked
# `is_mandatory` in the .proto, OR whose default scalar value (e.g. 0.0)
# would be omitted by `MessageToJson` and then read by the harness as
# "field not set". Keys are (containing_message_full_name, field_name).
_VALIDATOR_QUIRKS: dict[tuple[str, str], Any] = {
    # RegistrationValidator: icd_version must be the literal with spaces
    ("sapient_msg.bsi_flex_335_v2_0.Registration", "icd_version"): "BSI Flex 335 v2.0",
    # TaskDefinitionValidator: concurrent_tasks required
    ("sapient_msg.bsi_flex_335_v2_0.Registration.TaskDefinition", "concurrent_tasks"): 1,
    # StatusReportValidator: mode required, non-empty
    ("sapient_msg.bsi_flex_335_v2_0.StatusReport", "mode"): "default",
    # AlertValidator: ranking/confidence must be in [0,1] when set
    ("sapient_msg.bsi_flex_335_v2_0.Alert", "ranking"): 0.5,
    ("sapient_msg.bsi_flex_335_v2_0.Alert", "confidence"): 0.9,
    # DurationValidator: HasValue must be true. value=0.0 round-trips through
    # JSON as "absent" (proto3 default-omission), so use a non-zero placeholder.
    ("sapient_msg.bsi_flex_335_v2_0.Registration.Duration", "value"): 1.0,
}


def _field_opts(field: FieldDescriptor):
    return field.GetOptions().Extensions[_opts.field_options]


def _oneof_opts(oneof):
    return oneof.GetOptions().Extensions[_opts.oneof_options]


def _is_mandatory(field: FieldDescriptor) -> bool:
    return bool(_field_opts(field).is_mandatory)


def _is_ulid(field: FieldDescriptor) -> bool:
    return bool(_field_opts(field).is_ulid)


def _is_uuid(field: FieldDescriptor) -> bool:
    return bool(_field_opts(field).is_uuid)


def _quirk_value(parent_full_name: str, field_name: str):
    return _VALIDATOR_QUIRKS.get((parent_full_name, field_name))


def _first_non_zero_enum_value(field: FieldDescriptor) -> int:
    """Pick the first enum value that isn't UNSPECIFIED (zero)."""
    for v in field.enum_type.values:
        if v.number != 0:
            return v.number
    return 0  # only zero exists; will probably fail validation


def _placeholder_for_string(field: FieldDescriptor) -> str:
    """Pick the right placeholder for a string field."""
    if _is_ulid(field):
        return "{{ULID}}"
    if _is_uuid(field):
        return "{{NODE_ID}}"
    return f"sample-{field.name}"


def _is_synthetic_oneof(oneof) -> bool:
    """proto3 `optional` fields create a synthetic oneof named `_<field>`."""
    return oneof.name.startswith("_") and len(oneof.fields) == 1


def _populate_message(msg, *, depth: int = 0, max_depth: int = 8) -> None:
    """Set all mandatory fields on `msg` (and recurse into mandatory submessages)."""
    if depth > max_depth:
        return

    desc = msg.DESCRIPTOR

    # Real oneofs (multi-option choice). Pick the first option if the oneof is
    # mandatory or if any field in it is mandatory.
    real_oneofs = [o for o in desc.oneofs if not _is_synthetic_oneof(o)]
    handled_real_oneof_fields: set[str] = set()
    for oneof in real_oneofs:
        oneof_mandatory = bool(_oneof_opts(oneof).is_mandatory) or any(
            _is_mandatory(f) for f in oneof.fields
        )
        if not oneof_mandatory:
            continue
        chosen = oneof.fields[0]
        _set_field(msg, chosen, depth)
        for f in oneof.fields:
            handled_real_oneof_fields.add(f.name)

    for field in desc.fields:
        # Skip non-chosen members of real oneofs.
        if field.containing_oneof is not None and not _is_synthetic_oneof(field.containing_oneof):
            if field.name not in handled_real_oneof_fields:
                continue
            # Already populated above.
            continue

        quirk = _quirk_value(desc.full_name, field.name)
        if not _is_mandatory(field) and quirk is None:
            continue

        _set_field(msg, field, depth, override=quirk)


def _set_field(msg, field: FieldDescriptor, depth: int, *, override=None) -> None:
    """Set a single field on `msg` to a sensible default."""
    if field.label == FieldDescriptor.LABEL_REPEATED:
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            sub = getattr(msg, field.name).add()
            _populate_message(sub, depth=depth + 1)
        else:
            value = override if override is not None else _scalar_default(field)
            getattr(msg, field.name).append(value)
        return

    if field.type == FieldDescriptor.TYPE_MESSAGE:
        sub = getattr(msg, field.name)
        _populate_message(sub, depth=depth + 1)
        return

    if override is not None:
        setattr(msg, field.name, override)
        return

    setattr(msg, field.name, _scalar_default(field))


def _scalar_default(field: FieldDescriptor):
    t = field.type
    if t == FieldDescriptor.TYPE_STRING:
        return _placeholder_for_string(field)
    if t == FieldDescriptor.TYPE_BYTES:
        return b"\x01\x02\x03\x04"
    if t == FieldDescriptor.TYPE_BOOL:
        return True
    if t == FieldDescriptor.TYPE_ENUM:
        return _first_non_zero_enum_value(field)
    if t in (FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE):
        return 0.0
    if t in (FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
             FieldDescriptor.TYPE_UINT32, FieldDescriptor.TYPE_UINT64,
             FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
             FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64,
             FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64):
        return 0
    return None


def build_template_for_content(content_field_name: str) -> str:
    """Build a template JSON string for one `oneof content` case."""
    msg = _msg.SapientMessage()
    msg.node_id = "{{NODE_ID}}"
    # Populate the chosen content sub-message.
    content_desc = _msg.SapientMessage.DESCRIPTOR.fields_by_name[content_field_name]
    if content_desc.type != FieldDescriptor.TYPE_MESSAGE:
        raise ValueError(f"content field is not a message: {content_field_name}")
    sub = getattr(msg, content_field_name)
    _populate_message(sub, depth=1)
    # Force the timestamp to a sentinel so we can substitute below.
    msg.timestamp.seconds = 0
    msg.timestamp.nanos = 0

    raw = json_format.MessageToJson(
        msg, preserving_proto_field_name=True, indent=2, including_default_value_fields=False
    )
    # Replace the wrapper timestamp with the placeholder. Only the wrapper has
    # a top-level "timestamp" key (none of the inner SAPIENT messages do).
    raw = re.sub(
        r'"timestamp"\s*:\s*"1970-01-01T00:00:00Z"',
        '"timestamp": "{{NOW}}"',
        raw,
        count=1,
    )
    return raw + "\n"


def list_content_cases() -> list[str]:
    """Return every `oneof content` case in SapientMessage."""
    desc = _msg.SapientMessage.DESCRIPTOR
    oneof = desc.oneofs_by_name["content"]
    return [f.name for f in oneof.fields]


def regenerate_all(out_dir: Path = DEFAULT_TEMPLATES_DIR) -> dict[str, str]:
    """Regenerate one template per content case under out_dir.

    Returns map of {content_name: relative_path_written}. Existing files
    are overwritten.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for content_name in list_content_cases():
        body = build_template_for_content(content_name)
        # Validate the generated body parses back into a SapientMessage.
        # Substitute placeholders with concrete values for the validation parse.
        sample = (
            body.replace("{{NOW}}", "1970-01-01T00:00:00Z")
                .replace("{{NODE_ID}}", "00000000-0000-0000-0000-000000000000")
                .replace("{{ULID}}", "01HABCDEFGHJKMNPQRSTVWXYZ0")
        )
        check = _msg.SapientMessage()
        json_format.Parse(sample, check, ignore_unknown_fields=False)
        target = out_dir / f"{content_name}.json"
        target.write_text(body)
        written[content_name] = target.name
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Generate JSON templates for all SAPIENT content cases")
    p.add_argument("--out", default=str(DEFAULT_TEMPLATES_DIR),
                   help=f"output directory (default {DEFAULT_TEMPLATES_DIR})")
    p.add_argument("--list", action="store_true", help="list content cases and exit")
    args = p.parse_args(argv)

    if args.list:
        for name in list_content_cases():
            print(name)
        return 0

    written = regenerate_all(Path(args.out))
    for name, file in written.items():
        print(f"  {name:20s} -> {file}")
    print(f"wrote {len(written)} templates to {args.out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
