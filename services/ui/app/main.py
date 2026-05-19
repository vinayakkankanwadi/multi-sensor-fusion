"""FastAPI entrypoint for the UI.

Routes are split per drawer:

    services/ui/app/
    ├── nodes/    Nodes + Services drawers (proxied to services/nodes)
    ├── message/  Message drawer (templates, send, send_flow, validate, runs)
    └── tests/    Tests drawer (proxied to services/regression)

Each folder has a `routes.py` exposing a FastAPI `router`. This file
includes them and serves the static SPA + a top-level /api/health.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .apex.routes    import router as apex_router
from .message import proto_to_template, templates
from .message.routes import router as message_router
from .nodes.routes   import router as nodes_router
from .tests.routes   import router as tests_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


def _seed_templates_if_empty() -> None:
    """First-launch init: if data/templates/ has no .json files, build the
    canonical set from the SAPIENT .proto schema. Lets us keep data/ out
    of git — fresh clones (and fresh `docker compose up` against an empty
    bind mount) get a working set automatically."""
    out = templates.TEMPLATES_DIR
    out.mkdir(parents=True, exist_ok=True)
    if any(out.glob("*.json")):
        return
    written = proto_to_template.regenerate_all(out)
    log.info("ui startup: seeded %d templates into %s", len(written), out)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("ui startup")
    _seed_templates_if_empty()
    yield


app = FastAPI(title="ui", version="4",
              description="Template-driven SAPIENT BSI Flex 335 v2 sender + regression Tests drawer.",
              lifespan=_lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    # no-cache the shell so cache-busted /static/*?v=… queries are seen
    # immediately after a UI deploy.
    return FileResponse(STATIC_DIR / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


app.include_router(apex_router)
app.include_router(nodes_router)
app.include_router(message_router)
app.include_router(tests_router)
