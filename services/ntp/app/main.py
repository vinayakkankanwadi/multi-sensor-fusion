"""ntp — multi-source NTP probe service.

Periodically polls every NTP server in `NTP_SERVERS` (comma-separated,
default `pool.ntp.org`), and exposes:

    GET /ntp/current   the voted answer (median offset over reachable
                       servers) + worst severity, in the same shape the
                       single-server probe used to return.
    GET /ntp/sources   per-server detail: offset, rtt, severity, last_ok.
    GET /health        liveness.

One service centralises the cadence so we don't have N consumers each
hammering the upstream. The "voted" current offset uses the median of
all OK probes, which is robust against one server being skewed; if no
servers are reachable, `ok=False` and the worst per-server error is
surfaced.
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .probe import FAIL_THRESHOLD_S, WARN_THRESHOLD_S, NtpResult, query

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ntp")

DEFAULT_SERVERS = ["pool.ntp.org"]
DEFAULT_INTERVAL_S = 30.0
DEFAULT_TIMEOUT_S = 2.0

_SERVERS: list[str] = list(DEFAULT_SERVERS)
_INTERVAL_S: float = DEFAULT_INTERVAL_S
_TIMEOUT_S: float = DEFAULT_TIMEOUT_S

# Per-server latest result + when it last succeeded.
_PER_SOURCE: dict[str, dict] = {}
_VOTED: dict = {"ok": False, "error": "not yet probed", "severity": "fail"}

_POLL_TASK: asyncio.Task | None = None


def _vote(results: list[NtpResult]) -> dict:
    """Combine N per-server results into one 'system' answer.

    Strategy: median of the offsets of reachable servers. Severity is the
    *worst* across reachable servers — we'd rather warn loudly than hide
    a fail behind another server's ok.
    """
    ok_results = [r for r in results if r.ok and r.offset_s is not None]
    if not ok_results:
        worst_error = next(
            (r.error for r in results if r.error), "no reachable NTP sources")
        return {
            "ok": False,
            "offset_s": None,
            "rtt_s": None,
            "error": worst_error,
            "severity": "fail",
            "voted_from": 0,
            "asked": len(results),
            "warn_threshold_s": WARN_THRESHOLD_S,
            "fail_threshold_s": FAIL_THRESHOLD_S,
        }

    offsets = [r.offset_s for r in ok_results]
    median = statistics.median(offsets)
    abs_offset = abs(median)
    if abs_offset >= FAIL_THRESHOLD_S:
        sev = "fail"
    elif abs_offset >= WARN_THRESHOLD_S:
        sev = "warn"
    else:
        sev = "ok"

    severity_rank = {"ok": 0, "warn": 1, "fail": 2}
    worst = max((r.severity for r in ok_results), key=severity_rank.get)
    if severity_rank[worst] > severity_rank[sev]:
        sev = worst

    rtt = statistics.median([r.rtt_s for r in ok_results if r.rtt_s is not None]) \
        if any(r.rtt_s is not None for r in ok_results) else None

    return {
        "ok": True,
        "offset_s": median,
        "rtt_s": rtt,
        "error": None,
        "severity": sev,
        "voted_from": len(ok_results),
        "asked": len(results),
        "warn_threshold_s": WARN_THRESHOLD_S,
        "fail_threshold_s": FAIL_THRESHOLD_S,
    }


async def _probe_round() -> None:
    global _VOTED
    results = await asyncio.gather(
        *[query(server, timeout=_TIMEOUT_S) for server in _SERVERS]
    )
    now = time.time()
    for r in results:
        entry = _PER_SOURCE.get(r.server, {"first_seen": now})
        entry.update(r.to_dict())
        entry["last_probed_at"] = now
        if r.ok:
            entry["last_ok_at"] = now
        _PER_SOURCE[r.server] = entry
    _VOTED = _vote(results)
    log.info("probed %d/%d sources voted=%s offset=%s",
             _VOTED.get("voted_from", 0), len(_SERVERS),
             _VOTED.get("severity"),
             round(_VOTED["offset_s"], 4) if _VOTED.get("offset_s") is not None else None)


async def _poll_loop() -> None:
    while True:
        try:
            await _probe_round()
        except Exception as exc:
            log.warning("probe round failed: %s", exc)
        await asyncio.sleep(_INTERVAL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _SERVERS, _INTERVAL_S, _TIMEOUT_S, _POLL_TASK
    raw = os.environ.get("NTP_SERVERS", ",".join(DEFAULT_SERVERS))
    _SERVERS = [s.strip() for s in raw.split(",") if s.strip()]
    _INTERVAL_S = float(os.environ.get("NTP_INTERVAL_S", DEFAULT_INTERVAL_S))
    _TIMEOUT_S = float(os.environ.get("NTP_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    log.info("ntp starting: servers=%s interval=%ss timeout=%ss",
             _SERVERS, _INTERVAL_S, _TIMEOUT_S)
    # Probe once up front so /ntp/current has a real answer before the
    # first interval expires.
    try:
        await _probe_round()
    except Exception as exc:
        log.warning("initial probe failed: %s", exc)
    _POLL_TASK = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        if _POLL_TASK:
            _POLL_TASK.cancel()
            try:
                await _POLL_TASK
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(title="ntp",
              version="1",
              description="Multi-source NTP probe with HTTP read API.",
              lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "configured_servers": _SERVERS,
            "interval_s": _INTERVAL_S}


@app.get("/ntp/current")
def current() -> dict:
    """Voted offset across all configured NTP sources."""
    return dict(_VOTED)


@app.get("/ntp/sources")
def sources() -> dict:
    """Per-server detail: offset/rtt/severity/last-ok timestamps."""
    return {"servers": _SERVERS,
            "interval_s": _INTERVAL_S,
            "results": dict(_PER_SOURCE)}


@app.post("/ntp/refresh", status_code=200)
async def refresh_now() -> dict:
    """Force an immediate probe round so callers can avoid waiting
    `interval_s` after side-effects (e.g. the UI toggling a remote
    NTP server) before reading fresh state."""
    await _probe_round()
    return {"refreshed_at": time.time(),
            "results": dict(_PER_SOURCE),
            "voted": dict(_VOTED)}
