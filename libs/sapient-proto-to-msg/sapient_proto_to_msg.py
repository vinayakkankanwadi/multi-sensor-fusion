#!/usr/bin/env python3
"""sapient-proto-to-msg — convert SAPIENT .proto into the sapient_msg/ package.

Single Python entry point. Reads config.yaml (sibling of this file), runs
protoc inside an ephemeral docker container, and writes the result to
`<output_dir>/sapient_msg/`. The output is not committed: re-run this
script whenever the .proto sources or a service that consumes them needs
a fresh build.

Usage:
    python sapient_proto_to_msg.py                       # use config.yaml as-is
    python sapient_proto_to_msg.py --version bsi_flex_335_v1_0
    python sapient_proto_to_msg.py --output-dir /tmp/foo --lang python

Single source of truth (input):  dstl/SAPIENT-Proto-Files/
Output package:                  <output_dir>/sapient_msg/   (gitignored)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Add a new output language by adding an entry here. The string value is
# the protoc flag (=. ⇒ outputs into the cwd, which we set to the staging
# package root so generated import paths match what consumers expect).
TARGETS = {
    "python": "--python_out=.",
    # "go":   "--go_out=.",
    # "rust": "--rust_out=.",
}

# Pinned tool versions — these produce protobuf 4.x-compatible bindings
# (no `runtime_version` import, so services running protobuf 4.x don't
# crash at import time).
PROTOC_IMAGE = "python:3.12-slim"
PROTOC_PIP_DEPS = "'setuptools<70' 'grpcio-tools>=1.60,<1.63' 'protobuf>=4.25,<5'"

# Output package name. Consumers always import as `sapient_msg.<version>`,
# regardless of which lang you generate to.
PACKAGE = "sapient_msg"

HERE = Path(__file__).resolve().parent


def _load_config(path: Path) -> dict:
    """Minimal YAML reader for the fields we need (key: value lines only)."""
    cfg: dict = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        cfg[k.strip()] = v.strip()
    return cfg


def _resolve(base: Path, p: str) -> Path:
    """Resolve `p` relative to `base` if it isn't already absolute."""
    pp = Path(p)
    return (pp if pp.is_absolute() else (base / pp)).resolve()


def generate(*, proto_dir: Path, output_dir: Path, version: str, lang: str) -> Path:
    """Compile `proto_dir/<version>/*.proto` into `output_dir/sapient_msg/<version>/`.

    Returns the generated package directory.
    """
    if lang not in TARGETS:
        raise ValueError(f"unknown lang {lang!r}; known: {sorted(TARGETS)}")

    version_dir = proto_dir / version
    if not version_dir.is_dir():
        raise FileNotFoundError(f"no such version dir: {version_dir}")

    # Stage inputs under <PACKAGE>/ so generated imports use that prefix
    # (`from sapient_msg.<version> import sapient_message_pb2`).
    pkg_dir    = output_dir / PACKAGE
    stage_root = output_dir / "_stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_pkg = stage_root / PACKAGE
    stage_pkg.mkdir(parents=True)

    shared = proto_dir / "proto_options.proto"
    if shared.exists():
        shutil.copy2(shared, stage_pkg / "proto_options.proto")
    shutil.copytree(version_dir, stage_pkg / version)

    sources = []
    if shared.exists():
        sources.append(f"{PACKAGE}/proto_options.proto")
    sources.extend(
        f"{PACKAGE}/{version}/{p.name}" for p in sorted(version_dir.glob("*.proto"))
    )

    # Run protoc inside an ephemeral container. No host install required.
    protoc_cmd = (
        f"pip install --quiet {PROTOC_PIP_DEPS} && "
        f"python -m grpc_tools.protoc --proto_path=. {TARGETS[lang]} "
        + " ".join(sources)
    )
    subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{stage_root}:/stage",
            "-w", "/stage",
            PROTOC_IMAGE,
            "sh", "-c", protoc_cmd,
        ],
        check=True,
    )

    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    shutil.move(str(stage_pkg), str(pkg_dir))
    shutil.rmtree(stage_root)

    # Every directory in the package must be importable.
    for d in [pkg_dir, *[p for p in pkg_dir.rglob("*") if p.is_dir()]]:
        init = d / "__init__.py"
        if not init.exists():
            init.write_text("")

    return pkg_dir


def main(argv: list[str] | None = None) -> int:
    cfg_path = HERE / "config.yaml"
    cfg = _load_config(cfg_path)

    p = argparse.ArgumentParser(prog="sapient_proto_to_msg.py", description=__doc__)
    p.add_argument("--proto-dir",  default=cfg.get("proto_dir"),
                   help=f"default from config.yaml ({cfg.get('proto_dir')!r})")
    p.add_argument("--output-dir", default=cfg.get("output_dir", "."),
                   help=f"default from config.yaml ({cfg.get('output_dir')!r})")
    p.add_argument("--version",    default=cfg.get("version"),
                   help=f"default from config.yaml ({cfg.get('version')!r})")
    p.add_argument("--lang",       default=cfg.get("lang", "python"),
                   choices=sorted(TARGETS))
    args = p.parse_args(argv)

    proto_dir  = _resolve(HERE, args.proto_dir)
    output_dir = _resolve(HERE, args.output_dir)
    pkg = generate(proto_dir=proto_dir, output_dir=output_dir,
                   version=args.version, lang=args.lang)
    print(f"wrote: {pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
