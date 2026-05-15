#!/usr/bin/env bash
# Build orchestrator for multi-sensor-fusion.
#
# The proto bindings live in libs/sapient-proto/ and are baked into a
# small image (sapient-proto:latest) that ui and cot-bridge then
# COPY from at *their* build time. That image isn't in the default
# compose-up set, so a single `docker compose build` won't produce it.
# This wrapper builds it first (under the proto-build profile), then
# builds whatever else you asked for.
#
# Usage:
#   ./scripts/build.sh              # build everything
#   ./scripts/build.sh ui           # build the proto image, then just ui
#   ./scripts/build.sh ui cot-bridge

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/2] sapient-proto (proto bindings) ..."
docker compose --profile proto-build build sapient-proto

echo "[2/2] runtime services ($@) ..."
docker compose build "$@"

echo "Done."
