#!/usr/bin/env bash
# Regenerate Python protobuf bindings from ../../SAPIENT-Proto-Files/.
# The .proto files import as `sapient_msg/...`, so we stage them under a
# `sapient_msg/` directory before invoking protoc.
#
# Output: ./sapient_msg/  (Python package, committed alongside source).

set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
proto_root="$(cd "$here/../../SAPIENT-Proto-Files" && pwd)"
stage="$here/.proto_stage"
out="$here"

if [[ ! -d "$here/.venv" ]]; then
    echo "missing $here/.venv — run setup.sh first" >&2
    exit 2
fi

# Stage protos under a sapient_msg/ root so imports resolve.
rm -rf "$stage"
mkdir -p "$stage/sapient_msg"
cp "$proto_root/proto_options.proto" "$stage/sapient_msg/"
cp -r "$proto_root/bsi_flex_335_v2_0" "$stage/sapient_msg/"

# Wipe previously generated package to avoid stale files.
rm -rf "$out/sapient_msg"

# Generate. grpc_tools.protoc bundles a recent libprotoc that supports proto3 optional.
. "$here/.venv/bin/activate"
python -m grpc_tools.protoc \
    --proto_path="$stage" \
    --python_out="$out" \
    "$stage/sapient_msg/proto_options.proto" \
    "$stage"/sapient_msg/bsi_flex_335_v2_0/*.proto

# Make the generated tree a Python package.
touch "$out/sapient_msg/__init__.py"
touch "$out/sapient_msg/bsi_flex_335_v2_0/__init__.py"

rm -rf "$stage"

echo "generated $(find "$out/sapient_msg" -name '*_pb2.py' | wc -l) Python proto modules"
