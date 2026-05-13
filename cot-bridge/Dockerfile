# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Stage SAPIENT v2 protos via the named build context.
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

# Vendored converter library (sister folder via additional_contexts).
COPY --from=sapient-to-cot sapient_to_cot /app/sapient_to_cot

# App code.
COPY app/ /app/app/

EXPOSE 5005
CMD ["python", "-m", "app.main"]
