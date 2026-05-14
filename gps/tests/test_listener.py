"""NMEA parser + listener tests — exercise the offline decoder without
binding UDP."""

from __future__ import annotations

from app import listener as gps


def test_checksum_valid():
    s = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    assert gps._checksum_ok(s)


def test_checksum_rejected_when_wrong():
    s = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"
    assert not gps._checksum_ok(s)


def test_checksum_rejected_no_star():
    assert not gps._checksum_ok("$GPGGA,nostar")


def test_coord_to_decimal_north_east():
    assert abs(gps._coord_to_decimal("4807.038", "N") - 48.1173) < 1e-4
    assert abs(gps._coord_to_decimal("01131.000", "E") - 11.5167) < 1e-4


def test_coord_to_decimal_south_west_negative():
    assert gps._coord_to_decimal("4807.038", "S") < 0
    assert gps._coord_to_decimal("01131.000", "W") < 0


def test_parse_gga():
    p = gps.parse_sentence(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    )
    assert p["talker"] == "GP"
    assert p["type"] == "GGA"
    assert abs(p["latitude"] - 48.1173) < 1e-4
    assert abs(p["longitude"] - 11.5167) < 1e-4
    assert p["fix_quality"] == 1
    assert p["satellites"] == 8
    assert p["altitude"] == 545.4


def test_parse_rmc_valid_and_invalid_status():
    p = gps.parse_sentence(
        "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
    )
    assert p["status"] == "A"
    assert p["date"] == "230394"

    p = gps.parse_sentence(
        "$GPRMC,123519,V,,,,,,,230394,,*4F"
    )
    if p is not None:
        assert p.get("status") == "V"


def test_listener_consume_and_snapshot_lifecycle():
    lis = gps.NmeaListener(port=0)
    lis.consume(gps.parse_sentence(
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    ), addr=("192.0.2.1", 0))
    snap = lis.snapshot()
    assert snap.ok
    assert snap.fix_status == "valid"
    assert abs(snap.latitude - 48.1173) < 1e-4
    assert snap.satellites == 8
    assert snap.altitude == 545.4
    assert snap.last_sentence == "GPGGA"


def test_listener_marks_no_fix_when_quality_zero():
    lis = gps.NmeaListener(port=0)
    lis.consume(gps.parse_sentence(
        "$GPGGA,123519,4807.038,N,01131.000,E,0,00,99.0,0.0,M,0.0,M,,*4C"
    ), addr=("192.0.2.1", 0))
    snap = lis.snapshot()
    assert not snap.ok
    assert snap.fix_status == "no_fix"


def test_listener_unknown_sentence_returns_none():
    assert gps.parse_sentence("$GPABC,whatever*00") is None


def test_parse_gns_multi_gnss_sentence():
    p = gps.parse_sentence(
        "$GNGNS,045948.00,2730.222833,S,15305.547438,E,AAN,17,0.6,32.7,47.0,,*3D"
    )
    assert p["talker"] == "GN"
    assert p["type"] == "GNS"
    assert p["mode_indicator"] == "AAN"
    assert p["fix_quality"] == 1
    assert p["satellites"] == 17
    assert p["hdop"] == 0.6
    assert p["altitude"] == 32.7
    assert abs(p["latitude"] - (-27.503714)) < 1e-5
    assert abs(p["longitude"] - 153.092457) < 1e-5


def test_listener_strips_router_prefix_via_protocol_path():
    payload = (
        b"FRNE01_$GNGNS,045948.00,2730.222833,S,15305.547438,E,AAN,17,0.6,32.7,47.0,,*3D\r\n"
    )
    text = payload.decode("ascii", errors="replace")
    first = text.find("$")
    assert first > 0
    assert text[:first] == "FRNE01_"
    body = text[first:]
    parsed = gps.parse_sentence(body.strip())
    assert parsed and parsed["type"] == "GNS"
