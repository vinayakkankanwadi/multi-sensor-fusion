"""NMEA-over-UDP GPS listener.

Bind a UDP port and parse every incoming datagram as one-or-more NMEA
sentences (`$Gxxxx,...*HH` lines). The most recent fix is held in memory
and read via :meth:`NmeaListener.snapshot`.

Parser: minimal hand-written NMEA decoder for GGA / RMC / GLL / VTG / GSV
/ GNS. Avoids a third-party dep. Validates the `*HH` XOR checksum.
Coordinates are returned as signed decimal degrees.

Some gateways (Teltonika RutOS, for example) prepend a non-NMEA prefix
before the first `$` — we strip everything up to the first `$` so the
prefix doesn't break the parser.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)

DEFAULT_PORT = 8500
DEFAULT_BIND = "0.0.0.0"
STALE_AFTER_S = 10.0  # mark fix stale if no update within this window


@dataclass
class GpsFix:
    ok: bool
    error: str | None
    source: str
    fix_status: str | None       # "valid" / "no_fix"
    latitude: float | None       # decimal degrees, north positive
    longitude: float | None      # decimal degrees, east positive
    altitude: float | None       # metres MSL
    accuracy: float | None       # HDOP, lower = better
    satellites: int | None
    speed: float | None          # knots
    angle: float | None          # heading degrees true
    timestamp: str | None        # device-reported UTC, RFC3339
    last_sentence: str | None    # the last NMEA talker.type we parsed
    age_s: float | None          # seconds since last update
    raw: dict | None             # parsed raw fields for debugging

    def to_dict(self) -> dict:
        return asdict(self)


# --- NMEA parsing -----------------------------------------------------------

def _checksum_ok(sentence: str) -> bool:
    """Sentence is the full line beginning with '$' and ending with '*HH'."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, csum = sentence[1:].partition("*")
    csum = csum.strip()[:2]
    if not csum:
        return False
    actual = 0
    for ch in body:
        actual ^= ord(ch)
    try:
        return actual == int(csum, 16)
    except ValueError:
        return False


def _coord_to_decimal(value: str, hemi: str) -> float | None:
    """NMEA coords are DDMM.mmmm or DDDMM.mmmm — convert to signed decimal degrees."""
    if not value or not hemi:
        return None
    try:
        f = float(value)
    except ValueError:
        return None
    deg = int(f / 100)
    minutes = f - deg * 100
    decimal = deg + minutes / 60.0
    if hemi in ("S", "W"):
        decimal = -decimal
    return decimal


def _hms_dmy_to_iso(hhmmss: str, ddmmyy: str | None = None) -> str | None:
    if not hhmmss or len(hhmmss) < 6:
        return None
    h, m, s = hhmmss[:2], hhmmss[2:4], hhmmss[4:]
    if ddmmyy and len(ddmmyy) >= 6:
        dd, mm, yy = ddmmyy[:2], ddmmyy[2:4], ddmmyy[4:6]
        # NMEA two-digit year — assume 2000-2099.
        return f"20{yy}-{mm}-{dd}T{h}:{m}:{s}Z"
    return f"T{h}:{m}:{s}Z"  # no date — partial


def parse_sentence(sentence: str) -> dict | None:
    """Decode a single NMEA sentence into a dict of fields."""
    sentence = sentence.strip()
    if not _checksum_ok(sentence):
        return None
    body = sentence[1:].split("*", 1)[0]
    parts = body.split(",")
    talker_type = parts[0]
    if len(talker_type) < 5:
        return None
    typ = talker_type[2:]
    out: dict = {"talker": talker_type[:2], "type": typ}

    if typ == "GGA" and len(parts) >= 14:
        out.update({
            "time_utc": parts[1] or None,
            "latitude": _coord_to_decimal(parts[2], parts[3]),
            "longitude": _coord_to_decimal(parts[4], parts[5]),
            "fix_quality": int(parts[6]) if parts[6].isdigit() else 0,
            "satellites": int(parts[7]) if parts[7].isdigit() else 0,
            "hdop": float(parts[8]) if parts[8] else None,
            "altitude": float(parts[9]) if parts[9] else None,
        })
        return out

    if typ == "RMC" and len(parts) >= 12:
        out.update({
            "time_utc": parts[1] or None,
            "status": parts[2],
            "latitude": _coord_to_decimal(parts[3], parts[4]),
            "longitude": _coord_to_decimal(parts[5], parts[6]),
            "speed_knots": float(parts[7]) if parts[7] else None,
            "track_deg": float(parts[8]) if parts[8] else None,
            "date": parts[9] or None,
        })
        return out

    if typ == "GLL" and len(parts) >= 7:
        out.update({
            "latitude": _coord_to_decimal(parts[1], parts[2]),
            "longitude": _coord_to_decimal(parts[3], parts[4]),
            "time_utc": parts[5] or None,
            "status": parts[6],
        })
        return out

    if typ == "VTG" and len(parts) >= 9:
        out.update({
            "track_deg_true": float(parts[1]) if parts[1] else None,
            "speed_knots": float(parts[5]) if parts[5] else None,
            "speed_kph": float(parts[7]) if parts[7] else None,
        })
        return out

    if typ == "GSV" and len(parts) >= 4:
        out["satellites_in_view"] = int(parts[3]) if parts[3].isdigit() else None
        return out

    if typ == "GNS" and len(parts) >= 13:
        mode = (parts[6] or "")
        valid = any(ch != "N" for ch in mode)
        out.update({
            "time_utc": parts[1] or None,
            "latitude": _coord_to_decimal(parts[2], parts[3]),
            "longitude": _coord_to_decimal(parts[4], parts[5]),
            "mode_indicator": mode,
            "fix_quality": 1 if valid else 0,
            "satellites": int(parts[7]) if parts[7].isdigit() else 0,
            "hdop": float(parts[8]) if parts[8] else None,
            "altitude": float(parts[9]) if parts[9] else None,
            "geoid_separation": float(parts[10]) if parts[10] else None,
        })
        return out

    return None


# --- listener --------------------------------------------------------------

class _NmeaProtocol(asyncio.DatagramProtocol):
    def __init__(self, listener: "NmeaListener") -> None:
        self.listener = listener

    def datagram_received(self, data: bytes, addr) -> None:
        self.listener.record_raw(data, addr)
        try:
            text = data.decode("ascii", errors="replace")
        except Exception:
            return
        first_dollar = text.find("$")
        if first_dollar < 0:
            return
        if first_dollar > 0:
            self.listener.note_prefix(text[:first_dollar])
        body = text[first_dollar:]
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("$"):
                continue
            parsed = parse_sentence(line)
            if parsed is None:
                self.listener.note_unparsed(line)
                continue
            self.listener.consume(parsed, addr)


class NmeaListener:
    """Long-lived UDP listener; owns the latest fix."""

    def __init__(self, port: int = DEFAULT_PORT, bind: str = DEFAULT_BIND) -> None:
        self.port = port
        self.bind = bind
        self._fix = GpsFix(
            ok=False, error="no NMEA received yet",
            source=f"udp/{bind}:{port}",
            fix_status=None, latitude=None, longitude=None, altitude=None,
            accuracy=None, satellites=None, speed=None, angle=None,
            timestamp=None, last_sentence=None, age_s=None, raw=None,
        )
        self._last_update: float = 0.0
        self._transport: asyncio.DatagramTransport | None = None
        self._raw: dict = {}
        self._raw_datagrams: list[dict] = []
        self._unparsed: list[str] = []
        self._prefix_seen: str | None = None
        self._datagrams_total: int = 0
        self._sentences_parsed: int = 0
        self._sentences_unparsed: int = 0

    def record_raw(self, data: bytes, addr) -> None:
        self._datagrams_total += 1
        item = {
            "from": f"{addr[0]}:{addr[1]}",
            "bytes": len(data),
            "hex_first_64": data[:64].hex(),
            "ascii": data[:200].decode("ascii", errors="replace"),
        }
        self._raw_datagrams.append(item)
        if len(self._raw_datagrams) > 10:
            self._raw_datagrams.pop(0)

    def note_prefix(self, prefix: str) -> None:
        if prefix and prefix != self._prefix_seen:
            self._prefix_seen = prefix
            log.info("NMEA prefix detected: %r", prefix[:64])

    def note_unparsed(self, line: str) -> None:
        self._sentences_unparsed += 1
        self._unparsed.append(line)
        if len(self._unparsed) > 10:
            self._unparsed.pop(0)

    def stats(self) -> dict:
        return {
            "bound": f"{self.bind}:{self.port}",
            "datagrams_total": self._datagrams_total,
            "sentences_parsed": self._sentences_parsed,
            "sentences_unparsed": self._sentences_unparsed,
            "prefix_seen": self._prefix_seen,
            "last_datagrams": list(self._raw_datagrams),
            "last_unparsed_lines": list(self._unparsed),
        }

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _NmeaProtocol(self),
            local_addr=(self.bind, self.port),
        )
        log.info("NMEA listener bound to %s:%d", self.bind, self.port)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    def consume(self, parsed: dict, addr) -> None:
        typ = parsed.get("type")
        self._raw[typ] = parsed
        self._last_update = time.time()
        self._sentences_parsed += 1
        cur = self._fix
        lat = parsed.get("latitude")
        lon = parsed.get("longitude")
        alt = parsed.get("altitude")
        if lat is not None:
            cur.latitude = lat
        if lon is not None:
            cur.longitude = lon
        if alt is not None:
            cur.altitude = alt
        if "hdop" in parsed and parsed["hdop"] is not None:
            cur.accuracy = parsed["hdop"]
        if "satellites" in parsed and parsed["satellites"] is not None:
            cur.satellites = parsed["satellites"]
        if "speed_knots" in parsed and parsed["speed_knots"] is not None:
            cur.speed = parsed["speed_knots"]
        if "track_deg" in parsed:
            cur.angle = parsed["track_deg"]

        if typ == "RMC":
            cur.fix_status = "valid" if parsed.get("status") == "A" else "no_fix"
            iso = _hms_dmy_to_iso(parsed.get("time_utc", "") or "",
                                  parsed.get("date"))
            if iso and not iso.startswith("T"):
                cur.timestamp = iso
        elif typ in ("GGA", "GNS"):
            cur.fix_status = "valid" if parsed.get("fix_quality", 0) > 0 else "no_fix"
            iso_time = parsed.get("time_utc")
            if iso_time and len(iso_time) >= 6 and not cur.timestamp:
                from datetime import datetime, timezone
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                cur.timestamp = (
                    f"{today}T{iso_time[:2]}:{iso_time[2:4]}:{iso_time[4:]}Z"
                )

        cur.last_sentence = f"{parsed.get('talker')}{typ}"
        cur.source = f"udp/{self.bind}:{self.port} (from {addr[0]})"
        cur.ok = (cur.latitude is not None and cur.longitude is not None and
                  cur.fix_status == "valid")
        cur.error = None if cur.ok else (
            "no_fix" if cur.fix_status == "no_fix" else "incomplete fix")

    def snapshot(self) -> GpsFix:
        f = self._fix
        if self._last_update:
            f.age_s = round(time.time() - self._last_update, 3)
            if f.age_s and f.age_s > STALE_AFTER_S:
                stale = GpsFix(**asdict(f))
                stale.ok = False
                stale.error = f"stale fix ({f.age_s:.1f}s old)"
                stale.raw = self._raw
                return stale
        f.raw = self._raw
        return f
