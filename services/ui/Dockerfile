# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI + compose plugin for the apex controller, which shells out
# to `docker compose` to lifecycle the apex-gui and apex-sqlite-web
# services. Static binaries from docker's own release URL — no apt repo
# setup, no daemon installed inside the container; the host's daemon is
# reached via the /var/run/docker.sock bind mount declared in compose.
ARG DOCKER_VERSION=27.3.1
ARG COMPOSE_VERSION=2.29.7
RUN ARCH="$(uname -m)" && \
    curl -fsSL "https://download.docker.com/linux/static/stable/${ARCH}/docker-${DOCKER_VERSION}.tgz" \
      | tar -xz -C /usr/local/bin --strip-components=1 docker/docker && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose && \
    docker --version && docker compose version

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
