# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps (cache layer).
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Generated SAPIENT proto bindings — COPY the package directly (no pip
# install; this lib has no pyproject.toml because its output is just a
# folder you generate on demand). Regenerate with:
#   python libs/sapient-proto-to-msg/sapient_proto_to_msg.py
COPY --from=sapient-proto-to-msg sapient_msg /app/sapient_msg

# Python libs the service needs (proper pip packages).
COPY --from=sapient-encode-decode-msg . /tmp/_pkg/sapient-encode-decode-msg/
RUN pip install --no-cache-dir --no-deps /tmp/_pkg/sapient-encode-decode-msg && rm -rf /tmp/_pkg

# App code only — no test code in production images. Regression and library
# unit tests live in the root tests/ tree and run from a dedicated
# `regression` service container; see tests/README.md.
COPY app/ /app/app/

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
