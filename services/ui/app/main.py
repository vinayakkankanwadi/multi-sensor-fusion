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
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .message import proto_to_template, templates
from .message.routes import router as message_router
from .nodes.routes   import router as nodes_router
from .tests.routes   import router as tests_router

# Read-only view onto Apex's archive (bind-mounted from services/apex/data/).
APEX_ARCHIVE_DIR = Path("/app/apex-archive")

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


@app.get("/api/apex/stats")
def apex_stats() -> dict:
    """Summary over Apex's currently-rolling SQLite archive.

    Reads the most recent .sqlite file under /app/apex-archive (which is
    services/apex/data/ on the host). Apex writes WAL, so we open with
    immutable=0 and a short busy timeout.
    """
    if not APEX_ARCHIVE_DIR.exists():
        return {"available": False, "reason": "archive dir not mounted"}
    dbs = sorted(APEX_ARCHIVE_DIR.glob("data-*.sqlite"))
    if not dbs:
        return {"available": False, "reason": "no archive files yet"}
    latest = dbs[-1]
    try:
        c = sqlite3.connect(f"file:{latest}?mode=ro", uri=True, timeout=2)
        msg_total      = c.execute("SELECT COUNT(*) FROM Message").fetchone()[0]
        by_type        = dict(c.execute(
            "SELECT parsed_type, COUNT(*) FROM Message "
            "WHERE parsed_type IS NOT NULL "
            "GROUP BY parsed_type ORDER BY 2 DESC"))
        latest_ts      = c.execute("SELECT MAX(timestamp_received) FROM Message").fetchone()[0]
        conn_total     = c.execute("SELECT COUNT(*) FROM Connection").fetchone()[0]
        conn_open      = c.execute(
            "SELECT COUNT(*) FROM Connection WHERE disconnect_time IS NULL").fetchone()[0]
        c.close()
    except sqlite3.Error as exc:
        return {"available": False, "reason": f"sqlite: {exc}", "file": latest.name}
    return {
        "available": True,
        "file": latest.name,
        "all_files": [p.name for p in dbs],
        "messages_total": msg_total,
        "messages_by_type": by_type,
        "latest_received_us": latest_ts,
        "connections_total": conn_total,
        "connections_open": conn_open,
    }


app.include_router(nodes_router)
app.include_router(message_router)
app.include_router(tests_router)
