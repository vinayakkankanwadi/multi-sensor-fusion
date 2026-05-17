"""gps — health + NMEA listener (UDP-in, HTTP-out).

Injects NMEA datagrams on the real UDP socket and reads the parsed
snapshot back over HTTP, exercising the public "send NMEA in, get a fix
out" contract.
"""

from __future__ import annotations

import time


GGA          = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
GNS          = b"$GNGNS,045948.00,2730.222833,S,15305.547438,E,AAN,17,0.6,32.7,47.0,,*3D"
GGA_NO_FIX   = b"$GPGGA,123519,4807.038,N,01131.000,E,0,00,99.0,0.0,M,0.0,M,,*4C"
BAD_CHECKSUM = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"


def _wait_for_lat(http, gps_url, target_lat: float, atol: float = 1e-3,
                  timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cur = http.get(f"{gps_url}/gps/current").json()
        if cur.get("ok") and abs(cur.get("latitude", 0.0) - target_lat) < atol:
            return cur
        time.sleep(0.05)
    return http.get(f"{gps_url}/gps/current").json()


# ---------- health -------------------------------------------------------

def test_health(http, gps_url):
    r = http.get(f"{gps_url}/health")
    assert r.status_code == 200


# ---------- NMEA parsing into /gps/current -------------------------------

def test_gga_parsed_into_current(http, gps_url, udp_send, gps_nmea_endpoint):
    host, port = gps_nmea_endpoint
    udp_send(host, port, GGA + b"\r\n")
    cur = _wait_for_lat(http, gps_url, 48.1173)
    assert cur["ok"], cur
    assert abs(cur["latitude"]  - 48.1173) < 1e-3
    assert abs(cur["longitude"] - 11.5167) < 1e-3
    assert cur["satellites"] == 8
    assert cur["altitude"] == 545.4
    assert cur["fix_status"] == "valid"


def test_gns_multi_gnss_parsed_into_current(http, gps_url, udp_send,
                                            gps_nmea_endpoint):
    host, port = gps_nmea_endpoint
    udp_send(host, port, GNS + b"\r\n")
    cur = _wait_for_lat(http, gps_url, -27.503714, atol=1e-4)
    assert cur["ok"], cur
    assert cur["satellites"] == 17
    assert abs(cur["longitude"] - 153.092457) < 1e-4


def test_no_fix_gga_marks_snapshot_invalid(http, gps_url, udp_send,
                                            gps_nmea_endpoint):
    host, port = gps_nmea_endpoint
    udp_send(host, port, GGA_NO_FIX + b"\r\n")
    time.sleep(0.2)
    cur = http.get(f"{gps_url}/gps/current").json()
    assert cur["fix_status"] == "no_fix"
    assert cur["ok"] is False


def test_bad_checksum_does_not_overwrite_valid_fix(http, gps_url, udp_send,
                                                    gps_nmea_endpoint):
    host, port = gps_nmea_endpoint
    udp_send(host, port, GGA + b"\r\n")
    valid = _wait_for_lat(http, gps_url, 48.1173)
    assert valid["ok"]
    udp_send(host, port, BAD_CHECKSUM + b"\r\n")
    time.sleep(0.2)
    cur = http.get(f"{gps_url}/gps/current").json()
    assert abs(cur["latitude"] - 48.1173) < 1e-3


def test_raw_endpoint_exposes_last_datagrams(http, gps_url, udp_send,
                                              gps_nmea_endpoint):
    host, port = gps_nmea_endpoint
    udp_send(host, port, GGA + b"\r\n")
    time.sleep(0.2)
    r = http.get(f"{gps_url}/gps/raw")
    assert r.status_code == 200
    text = r.text.lower()
    assert "datagram" in text or "received" in text or "raw" in text or "hex" in text
