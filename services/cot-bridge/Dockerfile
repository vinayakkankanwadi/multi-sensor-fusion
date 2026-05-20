# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Generated SAPIENT proto bindings come from the build-only `proto-gen`
# compose service. No host-side codegen step.
COPY --from=sapient-proto-to-msg /work/sapient_msg /app/sapient_msg

# Python libs (proper pip packages).
COPY --from=sapient-encode-decode-msg   . /tmp/_pkg/sapient-encode-decode-msg/
COPY --from=sapient-msg-to-cot . /tmp/_pkg/sapient-msg-to-cot/
RUN pip install --no-cache-dir --no-deps \
        /tmp/_pkg/sapient-encode-decode-msg \
        /tmp/_pkg/sapient-msg-to-cot \
    && rm -rf /tmp/_pkg

COPY app/ /app/app/

EXPOSE 5005 8092
CMD ["python", "-m", "app.main"]
