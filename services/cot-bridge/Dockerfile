# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# SAPIENT v2 Python bindings, generated in libs/sapient-proto/ and pulled
# in via the proto-bindings additional_context (a docker image).
COPY --from=proto-bindings /sapient_msg /app/sapient_msg

# Shared length-prefix framer (libs/sapient-wire/).
COPY --from=sapient-wire sapient_wire /app/sapient_wire

# Vendored converter library (sister folder via additional_contexts).
COPY --from=sapient-to-cot sapient_to_cot /app/sapient_to_cot
# Bake the converter's own tests in so the README's
#   docker exec cot-bridge python -m pytest /app/sapient_to_cot
# command actually works post-deploy.
COPY --from=sapient-to-cot tests /app/sapient_to_cot/tests
RUN pip install --no-cache-dir 'pytest>=7'

# App code.
COPY app/ /app/app/

EXPOSE 5005
CMD ["python", "-m", "app.main"]
