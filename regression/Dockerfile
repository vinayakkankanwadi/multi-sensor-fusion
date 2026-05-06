# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cache layer).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Stage SAPIENT protos from the named build context "proto-src" into
# /app/proto-src/sapient_msg/ so import paths resolve.
COPY --from=proto-src proto_options.proto /app/proto-src/sapient_msg/proto_options.proto
COPY --from=proto-src bsi_flex_335_v2_0   /app/proto-src/sapient_msg/bsi_flex_335_v2_0

# Generate Python bindings into /app/sapient_msg/.
RUN python -m grpc_tools.protoc \
        --proto_path=/app/proto-src \
        --python_out=/app \
        /app/proto-src/sapient_msg/proto_options.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/alert.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/alert_ack.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/associated_detection.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/associated_file.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/detection_report.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/error.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/follow.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/location.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/range_bearing.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/registration.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/registration_ack.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/sapient_message.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/status_report.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/task.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/task_ack.proto \
        /app/proto-src/sapient_msg/bsi_flex_335_v2_0/velocity.proto \
    && touch /app/sapient_msg/__init__.py /app/sapient_msg/bsi_flex_335_v2_0/__init__.py \
    && rm -rf /app/proto-src

# SAPIENT → CoT converter package, baked in alongside the app.
COPY --from=sapient-to-cot sapient_to_cot /app/sapient_to_cot

# App code + tests (tests baked in so `docker exec ... pytest` works).
COPY app/ /app/app/
COPY tests/ /app/tests/

# pytest as a runtime dep — small, useful for in-container regression runs.
RUN pip install --no-cache-dir 'pytest>=7'

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
