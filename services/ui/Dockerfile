# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cache layer).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# SAPIENT BSI Flex 335 v2 Python bindings, generated in libs/sapient-proto/
# and pulled in via the proto-bindings additional_context (a docker image).
COPY --from=proto-bindings /sapient_msg /app/sapient_msg

# Shared length-prefix framer (libs/sapient-wire/).
COPY --from=sapient-wire sapient_wire /app/sapient_wire

# App code + tests (tests baked in so `docker exec ... pytest` works).
COPY app/ /app/app/
COPY tests/ /app/tests/

# pytest as a runtime dep — small, useful for in-container test runs.
RUN pip install --no-cache-dir 'pytest>=7'

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
