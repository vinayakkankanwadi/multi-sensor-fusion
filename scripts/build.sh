#!/usr/bin/env bash
# Build orchestrator for multi-sensor-fusion.
#
# Steps:
#   1. Regenerate the SAPIENT proto bindings (libs/sapient-proto-to-msg/
#      runs protoc inside an ephemeral container; output goes to
#      libs/sapient-proto-to-msg/sapient_msg/, which is gitignored).
#   2. docker compose build.
#
# Re-running is idempotent and cheap (the regenerator skips work if the
# .proto sources are unchanged is a future optimisation; for now it
# rebuilds every time, which is still seconds).
#
# Usage:
#   ./scripts/build.sh                    # build everything
#   ./scripts/build.sh ui                 # build just ui (still regen first)
#   ./scripts/build.sh ui cot-bridge

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/2] regenerating SAPIENT proto bindings ..."
python3 libs/sapient-proto-to-msg/sapient_proto_to_msg.py

echo "[2/2] docker compose build $* ..."
docker compose build "$@"
