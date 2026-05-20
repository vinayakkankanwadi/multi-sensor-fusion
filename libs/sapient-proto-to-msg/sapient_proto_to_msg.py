#!/usr/bin/env python3
"""sapient-proto-to-msg — generate the sapient_msg/ package from .proto sources.

Runs `grpc_tools.protoc` directly. Caller must have `grpcio-tools`
installed (the proto-gen Dockerfile in this directory does that;
locally: `pip install 'grpcio-tools>=1.60,<1.63' 'protobuf>=4.25,<5'`).
Output is gitignored: re-run whenever the proto sources change.

    python sapient_proto_to_msg.py
    python sapient_proto_to_msg.py --version bsi_flex_335_v1_0
    python sapient_proto_to_msg.py --output-dir /tmp/foo
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TARGETS = {"python": "--python_out=."}

PACKAGE = "sapient_msg"

HERE = Path(__file__).resolve().parent

# Defaults — override with CLI flags.
DEFAULT_PROTO_DIR  = "../../dstl/SAPIENT-Proto-Files"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_VERSION    = "bsi_flex_335_v2_0"
DEFAULT_LANG       = "python"


def _resolve(base: Path, p: str) -> Path:
    pp = Path(p)
    return (pp if pp.is_absolute() else (base / pp)).resolve()


def generate(*, proto_dir: Path, output_dir: Path, version: str, lang: str) -> Path:
    if lang not in TARGETS:
        raise ValueError(f"unknown lang {lang!r}; known: {sorted(TARGETS)}")

    version_dir = proto_dir / version
    if not version_dir.is_dir():
        raise FileNotFoundError(f"no such version dir: {version_dir}")

    # Stage inputs under <PACKAGE>/ so generated imports use that prefix.
    pkg_dir    = output_dir / PACKAGE
    stage_root = output_dir / "_stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_pkg = stage_root / PACKAGE
    stage_pkg.mkdir(parents=True)

    shared = proto_dir / "proto_options.proto"
    sources: list[str] = []
    if shared.exists():
        shutil.copy2(shared, stage_pkg / "proto_options.proto")
        sources.append(f"{PACKAGE}/proto_options.proto")
    shutil.copytree(version_dir, stage_pkg / version)
    sources.extend(
        f"{PACKAGE}/{version}/{p.name}" for p in sorted(version_dir.glob("*.proto"))
    )

    subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc",
         "--proto_path=.", TARGETS[lang], *sources],
        cwd=stage_root,
        check=True,
    )

    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    shutil.move(str(stage_pkg), str(pkg_dir))
    shutil.rmtree(stage_root)

    for d in [pkg_dir, *(p for p in pkg_dir.rglob("*") if p.is_dir())]:
        init = d / "__init__.py"
        if not init.exists():
            init.write_text("")

    return pkg_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sapient_proto_to_msg.py", description=__doc__)
    p.add_argument("--proto-dir",  default=DEFAULT_PROTO_DIR)
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--version",    default=DEFAULT_VERSION)
    p.add_argument("--lang",       default=DEFAULT_LANG, choices=sorted(TARGETS))
    args = p.parse_args(argv)

    pkg = generate(
        proto_dir=_resolve(HERE, args.proto_dir),
        output_dir=_resolve(HERE, args.output_dir),
        version=args.version, lang=args.lang,
    )
    print(f"wrote: {pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
