"""msf-gps — NMEA-over-UDP aggregator service.

Owns UDP/MSF_NMEA_PORT (default 8500) and aggregates incoming NMEA from
one or more upstream sources (router-pushed today; drone-borne GPS over
SAPIENT detections planned). Every consumer (UI, future fusion node, …)
asks this service for the current fix via HTTP — there is exactly one
NMEA listener in the system, regardless of how many readers there are.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .listener import DEFAULT_BIND, DEFAULT_PORT, NmeaListener

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("msf-gps")

listener: NmeaListener | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global listener
    port = int(os.environ.get("MSF_NMEA_PORT", str(DEFAULT_PORT)))
    bind = os.environ.get("MSF_NMEA_BIND", DEFAULT_BIND)
    listener = NmeaListener(port=port, bind=bind)
    await listener.start()
    log.info("msf-gps startup complete (NMEA on %s:%d)", bind, port)
    try:
        yield
    finally:
        await listener.stop()


app = FastAPI(title="msf-gps",
              version="1",
              description="NMEA-over-UDP listener with HTTP read API for the latest GPS fix.",
              lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "listener_bound": listener is not None}


@app.get("/gps/current")
def current() -> dict:
    """Latest aggregated GPS fix. Always returns a fix object — check
    `ok` for validity and `error` for the reason if not."""
    if listener is None:
        return {"ok": False, "error": "listener not running",
                "source": "(none)",
                "fix_status": None, "latitude": None, "longitude": None,
                "altitude": None, "accuracy": None, "satellites": None,
                "speed": None, "angle": None, "timestamp": None,
                "last_sentence": None, "age_s": None, "raw": None}
    return listener.snapshot().to_dict()


@app.get("/gps/raw")
def raw() -> dict:
    """Listener stats + the last few raw datagrams (hex + ascii) so
    operators can see what the upstream is actually pushing — including
    any prefix the gateway prepends before the NMEA `$`."""
    if listener is None:
        return {"error": "listener not running"}
    return listener.stats()
