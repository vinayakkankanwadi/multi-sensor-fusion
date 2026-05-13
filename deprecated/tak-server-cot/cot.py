"""Cursor-on-Target (CoT) message builder + UDP sender.

CoT is the XML format ATAK / WinTAK / iTAK clients display on the map and
that TAK Server ingests on its CoT input port (TCP 8087 by default,
configurable to a UDP listener). This module writes well-formed CoT XML
matching the schema TAK Server expects.

References:
  - MITRE CoT specification (2002 onwards) — the `event` / `point` / `detail` shape.
  - 2525C / MIL-STD-2525 symbol codes used in `event.type`, e.g.:
        a-f-G-U-C  Atom · Friend · Ground · Unit · Combat
        a-f-G-E-V  Atom · Friend · Ground · Equipment · Vehicle
        a-h-G-U-C  Atom · Hostile · Ground · Unit · Combat
        a-n-G      Atom · Neutral · Ground
        a-u-G      Atom · Unknown · Ground
"""

from __future__ import annotations

import argparse
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, tostring


def utc(t: datetime) -> str:
    """Return ISO-8601 zulu time with millisecond precision (TAK convention)."""
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def build_cot(
    *,
    uid: str,
    cot_type: str = "a-f-G-U-C",
    lat: float = 0.0,
    lon: float = 0.0,
    hae: float = 0.0,
    ce: float = 9999999.0,
    le: float = 9999999.0,
    callsign: str = "MSF-Edge",
    group_name: str = "Cyan",
    group_role: str = "Team Member",
    stale_seconds: int = 300,
    how: str = "m-g",
    remarks: str | None = None,
) -> bytes:
    """Build one CoT event as XML bytes (ASCII)."""
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=stale_seconds)

    event = Element("event", {
        "version": "2.0",
        "uid": uid,
        "type": cot_type,
        "time": utc(now),
        "start": utc(now),
        "stale": utc(stale),
        "how": how,
    })
    SubElement(event, "point", {
        "lat": f"{lat:.7f}",
        "lon": f"{lon:.7f}",
        "hae": f"{hae:.3f}",
        "ce":  f"{ce:.1f}",
        "le":  f"{le:.1f}",
    })
    detail = SubElement(event, "detail")
    SubElement(detail, "contact", {"callsign": callsign})
    SubElement(detail, "__group", {"name": group_name, "role": group_role})
    SubElement(detail, "precisionlocation", {"altsrc": "GPS", "geopointsrc": "GPS"})
    if remarks:
        r = SubElement(detail, "remarks")
        r.text = remarks
    # XML declaration + body, no pretty-print (TAK happily ingests both).
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(event)


def send_udp(payload: bytes, host: str, port: int, *, timeout: float = 2.0) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        return sock.sendto(payload, (host, port))
    finally:
        sock.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--host", default="192.168.201.102", help="TAK server IP")
    p.add_argument("--port", type=int, default=6969, help="TAK CoT UDP port")
    p.add_argument("--uid",  default=None, help="UID (default: a fresh UUID)")
    p.add_argument("--callsign", default="MSF-Edge", help="callsign shown on map")
    p.add_argument("--type", dest="cot_type", default="a-f-G-U-C",
                   help="CoT type (default a-f-G-U-C = friend ground unit combat)")
    p.add_argument("--lat", type=float, default=-27.503742,
                   help="latitude (decimal degrees)")
    p.add_argument("--lon", type=float, default=153.092451,
                   help="longitude (decimal degrees)")
    p.add_argument("--hae", type=float, default=29.7,
                   help="height above ellipsoid (m)")
    p.add_argument("--stale", type=int, default=300,
                   help="staleness in seconds (default 5 min)")
    p.add_argument("--remarks", default=None, help="freeform remarks line")
    p.add_argument("--print", dest="print_xml", action="store_true",
                   help="print the XML before sending")
    p.add_argument("--repeat", type=int, default=1,
                   help="send N copies (use --interval to space them)")
    p.add_argument("--interval", type=float, default=1.0,
                   help="seconds between repeats")
    args = p.parse_args(argv)

    uid = args.uid or f"MSF-{uuid.uuid4()}"
    sent_total = 0
    import time
    for i in range(args.repeat):
        xml = build_cot(
            uid=uid, cot_type=args.cot_type,
            lat=args.lat, lon=args.lon, hae=args.hae,
            callsign=args.callsign, stale_seconds=args.stale,
            remarks=args.remarks,
        )
        if args.print_xml:
            sys.stdout.write(xml.decode("ascii") + "\n")
        n = send_udp(xml, args.host, args.port)
        sent_total += n
        print(f"sent {n} bytes -> udp://{args.host}:{args.port}  uid={uid}  "
              f"[{i + 1}/{args.repeat}]")
        if i + 1 < args.repeat:
            time.sleep(args.interval)
    print(f"done: {sent_total} bytes total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
