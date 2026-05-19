# syntax=docker/dockerfile:1.6
FROM python:3.11-slim

WORKDIR /app

# ca-certificates: needed for pip/elastic over https.
# xcb + xkb + gl + fontconfig + dbus: PySide6's Qt runtime needs these
# for the apex-gui compose service (X11 forwarded from the host). They
# add ~50 MB to the image; the GUI variant uses them, the middleware
# variant ignores them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libglib2.0-0 libxkbcommon0 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
        libxcb-xkb1 libxkbcommon-x11-0 \
        libegl1 libgl1 libfontconfig1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

# Pull the Apex source from the vendored folder via additional_contexts.
COPY --from=apex-src . /app/

# Local patches over vendored Apex. Each is a Python script that does an
# idempotent in-place edit. Rationale is at the top of each .py file.
# Tracks dstl/Apex-SAPIENT-Middleware issue (filed) — remove once merged.
COPY patches/ /app/_patches/
RUN set -e; for p in /app/_patches/*.py; do \
        echo "==> applying $(basename "$p")"; \
        python "$p"; \
    done

# Full dependency set: middleware + GUI + replay all run from the same
# image, selected per-service via compose `command:`.
RUN pip install --no-cache-dir \
        'protobuf>=4.25.1,<5' \
        'trio==0.23.1' \
        'ulid-py>=1.1' \
        'fastapi>=0.104' \
        'uvicorn>=0.24' \
        'httpx>=0.26' \
        'sqlalchemy>=2.0' \
        'pydantic>=2' \
        'elasticsearch>=8.11,<9' \
        'pyside6==6.5.1.1'

# Apex queries its own package metadata at startup (importlib.metadata).
# Install the project itself so `metadata("apex")` resolves.
RUN pip install --no-cache-dir --no-deps /app

# Our LAN-specific config is volume-mounted; bake a placeholder so the
# image still starts standalone if no volume is provided.
COPY apex_config.json /app/apex_config.json

EXPOSE 5000 5010 5020 5001 5003 5004 8081

# Health: Apex's REST root returns 200 once the server is up. Uses
# Python's stdlib so we don't drag curl into the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; \
                   urllib.request.urlopen('http://127.0.0.1:8081/', timeout=3).read()" \
        || exit 1

CMD ["python", "-m", "sapient_apex_server.apex"]
