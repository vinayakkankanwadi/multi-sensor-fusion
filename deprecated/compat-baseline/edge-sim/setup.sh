#!/usr/bin/env bash
# One-time setup for the Ubuntu-side capture harness.
#
# Creates compat-baseline/capture/.venv, installs Python deps, generates
# protobuf bindings from ../../SAPIENT-Proto-Files/bsi_flex_335_v2_0/.
#
# Re-run this if SAPIENT-Proto-Files/ is updated upstream.

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if command -v "/home/ubuntu20/.pyenv/versions/3.10.13/bin/python3" >/dev/null 2>&1; then
    PYTHON_BIN="/home/ubuntu20/.pyenv/versions/3.10.13/bin/python3"
fi

if [[ ! -d .venv ]]; then
    "$PYTHON_BIN" -m venv .venv
fi

. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

./generate_proto.sh

echo "setup complete; activate the venv with: . compat-baseline/capture/.venv/bin/activate"
