"""Tests for the sapient-proto-to-msg generator.

Two layers:
  1. Pure-Python helpers in the script (config parsing, path resolution).
  2. The generator's output — every message type from the v2 ICD has
     been emitted, is importable, and has the expected oneof shape.

The actual protoc invocation is NOT exercised here (it spins up a docker
container; that work is done at image build time and the result is what
we're verifying). If the build step failed, sapient_msg wouldn't be
importable and these tests would fail loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sapient_proto_to_msg as gen


# ---------- pure-Python helpers ------------------------------------------

def test_config_yaml_loads_required_keys():
    """The shipping config.yaml must declare proto_dir, version, output_dir, lang."""
    cfg = gen._load_config(Path("/opt/config.yaml"))
    for key in ("proto_dir", "version", "output_dir", "lang"):
        assert key in cfg, f"missing key in config.yaml: {key}"


def test_config_default_version_is_v2():
    """v2 is the active ICD; the shipping config must default to it."""
    cfg = gen._load_config(Path("/opt/config.yaml"))
    assert cfg["version"] == "bsi_flex_335_v2_0"


def test_config_default_lang_is_python():
    cfg = gen._load_config(Path("/opt/config.yaml"))
    assert cfg["lang"] == "python"


def test_resolve_absolute_path_unchanged(tmp_path):
    assert gen._resolve(tmp_path, str(tmp_path / "x")) == (tmp_path / "x").resolve()


def test_resolve_relative_path_joins_with_base(tmp_path):
    target = tmp_path / "sub" / "file.txt"
    target.parent.mkdir()
    target.write_text("x")
    assert gen._resolve(tmp_path, "sub/file.txt") == target.resolve()


def test_targets_dict_has_python():
    assert "python" in gen.TARGETS
    assert gen.TARGETS["python"].startswith("--python_out")


def test_unknown_lang_rejected(tmp_path):
    """generate() raises on unknown languages so typos don't silently no-op."""
    with pytest.raises(ValueError, match="unknown lang"):
        gen.generate(
            proto_dir=tmp_path, output_dir=tmp_path,
            version="bsi_flex_335_v2_0", lang="cobol",
        )


# ---------- output verification ------------------------------------------

EXPECTED_V2_MESSAGES = {
    "alert",       "alert_ack",
    "task",        "task_ack",
    "registration", "registration_ack",
    "status_report", "detection_report",
    "error",
}

# These are types embedded in messages above; their .proto files must
# compile too, otherwise the message imports fail.
EXPECTED_V2_SUPPORT = {
    "associated_detection", "associated_file",
    "follow", "location", "range_bearing", "velocity",
    "sapient_message",
}


def test_v2_package_importable():
    """The umbrella SapientMessage type must import — proves the generator
    produced a working package."""
    from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2
    assert hasattr(sapient_message_pb2, "SapientMessage")


def test_every_expected_message_pb2_exists():
    base = Path("/opt/sapient_msg/bsi_flex_335_v2_0")
    for name in EXPECTED_V2_MESSAGES | EXPECTED_V2_SUPPORT:
        assert (base / f"{name}_pb2.py").is_file(), f"missing {name}_pb2.py"


def test_sapient_message_oneof_contains_every_content_case():
    """The SapientMessage `content` oneof is the spec's source of truth for
    which message types the wire format supports — verify every expected
    case is present."""
    from sapient_msg.bsi_flex_335_v2_0 import sapient_message_pb2
    msg = sapient_message_pb2.SapientMessage()
    oneof = msg.DESCRIPTOR.oneofs_by_name["content"]
    field_names = {f.name for f in oneof.fields}
    assert EXPECTED_V2_MESSAGES <= field_names, (
        f"missing oneof fields: {EXPECTED_V2_MESSAGES - field_names}"
    )


def test_v1_artifacts_not_shipped_by_default():
    """Default config targets v2 only — v1 bindings should be absent."""
    assert not Path("/opt/sapient_msg/bsi_flex_335_v1_0").exists(), (
        "v1 directory present; config.yaml is supposed to default to v2 only"
    )


def test_package_init_files_present():
    """Every package directory needs __init__.py to be importable."""
    base = Path("/opt/sapient_msg")
    assert (base / "__init__.py").is_file()
    assert (base / "bsi_flex_335_v2_0" / "__init__.py").is_file()
