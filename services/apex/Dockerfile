# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pull the Apex source from the vendored folder via additional_contexts.
COPY --from=apex-src . /app/

# Install the headless dependency subset (skip PySide6 GUI etc.).
RUN pip install --no-cache-dir \
        'protobuf>=4.25.1,<5' \
        'trio==0.23.1' \
        'ulid-py>=1.1' \
        'fastapi>=0.104' \
        'uvicorn>=0.24' \
        'httpx>=0.26' \
        'sqlalchemy>=2.0' \
        'pydantic>=2' \
        'elasticsearch>=8.11,<9'

# Apex queries its own package metadata at startup (importlib.metadata).
# Install the project itself so `metadata("apex")` resolves.
RUN pip install --no-cache-dir --no-deps /app

# Our LAN-specific config is volume-mounted; bake a placeholder so the
# image still starts standalone if no volume is provided.
COPY apex_config.json /app/apex_config.json

EXPOSE 5000 5010 5020 5001 5003 5004 8081
CMD ["python", "-m", "sapient_apex_server.apex"]
