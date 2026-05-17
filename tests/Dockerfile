# syntax=docker/dockerfile:1.6
# Regression test runner — self-contained, lib-agnostic.
#
# Adding a new pip-installable library: drop libs/<name>/{<package>,pyproject.toml}
# plus tests/libs/<name>/test_*.py and rebuild. This image COPYs the
# whole libs/ tree once, pip-installs every lib that has a
# pyproject.toml, and pytest auto-discovers everything under tests/.
# No edits here, no edits to docker-compose.yml.
#
# The generated SAPIENT proto bindings are a special case: they live as
# a folder you generate on demand (no pyproject.toml), so we COPY them
# straight onto PYTHONPATH like any consuming service does.
FROM python:3.12-slim

WORKDIR /work

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# sapient-proto-to-msg is a special case: not a pip-installable lib, so
# we COPY both its output (sapient_msg/, used by every consumer) and its
# script + config (so test_generator.py can import the script's helpers
# and verify the shipping config). Everything lives under /opt — on
# PYTHONPATH — so the libs COPY below doesn't shadow them.
COPY --from=sapient-proto-to-msg sapient_msg              /opt/sapient_msg
COPY --from=sapient-proto-to-msg sapient_proto_to_msg.py  /opt/sapient_proto_to_msg.py
COPY --from=sapient-proto-to-msg config.yaml              /opt/config.yaml

# Pip-installable libraries — discovered by wildcard (a lib without a
# pyproject.toml, like sapient-proto-to-msg, gets skipped here on purpose).
COPY --from=libs-root . /tmp/libs/
RUN set -e; \
    for d in /tmp/libs/*/; do \
        if [ -f "$d/pyproject.toml" ]; then \
            echo "installing $d"; \
            pip install --no-cache-dir --no-deps "$d"; \
        fi; \
    done && rm -rf /tmp/libs

# The whole tests tree — tests/libs/ (library unit tests) + tests/services/
# (black-box service tests) + shared conftest. pytest auto-discovers both
# subtrees from /work/tests.
COPY . /work/tests/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt

CMD ["pytest", "-v", "--tb=short", "--color=yes", "-p", "no:cacheprovider", \
     "-c", "/work/tests/pytest.ini", "/work/tests"]
