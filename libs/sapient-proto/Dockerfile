# syntax=docker/dockerfile:1.6
#
# sapient-proto — build-only image that holds the generated Python
# bindings for SAPIENT BSI Flex 335 v2. The image's only job is to be a
# COPY source for the runtime services. It is never `compose up`'d.
#
# Consumers (ui, cot-bridge) reference it via:
#
#     additional_contexts:
#       proto-bindings: docker-image://sapient-proto:latest
#
# and then `COPY --from=proto-bindings /sapient_msg /app/sapient_msg`.
#
# The protoc invocation lives here (and only here) so adding a future
# proto file is a one-line edit to one Dockerfile, not three.

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir 'grpcio-tools>=1.50' 'protobuf>=4.21,<5'

WORKDIR /work
COPY --from=proto-src proto_options.proto /work/sapient_msg/proto_options.proto
COPY --from=proto-src bsi_flex_335_v2_0   /work/sapient_msg/bsi_flex_335_v2_0

RUN python -m grpc_tools.protoc \
        --proto_path=. \
        --python_out=. \
        sapient_msg/proto_options.proto \
        sapient_msg/bsi_flex_335_v2_0/alert.proto \
        sapient_msg/bsi_flex_335_v2_0/alert_ack.proto \
        sapient_msg/bsi_flex_335_v2_0/associated_detection.proto \
        sapient_msg/bsi_flex_335_v2_0/associated_file.proto \
        sapient_msg/bsi_flex_335_v2_0/detection_report.proto \
        sapient_msg/bsi_flex_335_v2_0/error.proto \
        sapient_msg/bsi_flex_335_v2_0/follow.proto \
        sapient_msg/bsi_flex_335_v2_0/location.proto \
        sapient_msg/bsi_flex_335_v2_0/range_bearing.proto \
        sapient_msg/bsi_flex_335_v2_0/registration.proto \
        sapient_msg/bsi_flex_335_v2_0/registration_ack.proto \
        sapient_msg/bsi_flex_335_v2_0/sapient_message.proto \
        sapient_msg/bsi_flex_335_v2_0/status_report.proto \
        sapient_msg/bsi_flex_335_v2_0/task.proto \
        sapient_msg/bsi_flex_335_v2_0/task_ack.proto \
        sapient_msg/bsi_flex_335_v2_0/velocity.proto \
    && touch sapient_msg/__init__.py sapient_msg/bsi_flex_335_v2_0/__init__.py

# Final image: scratch, contains only the bindings.
FROM scratch
COPY --from=builder /work/sapient_msg /sapient_msg
