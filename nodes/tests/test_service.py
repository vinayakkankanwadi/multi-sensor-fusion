"""service probe — offline tests (real loopback HTTP/TCP + synthetic failures)."""

from __future__ import annotations

import asyncio
import http.server
import socket
import threading

from app.probes import service


def _run(entry):
    return asyncio.run(service.probe(entry, {}))


# --- HTTP probe ------------------------------------------------------------

class _OK(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')
    def log_message(self, *a): pass


class _Err500(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500)
        self.end_headers()
    def log_message(self, *a): pass


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def test_http_probe_ok_for_2xx():
    srv = _serve(_OK)
    try:
        port = srv.server_address[1]
        n = _run({"id": "x", "type": "service", "name": "x",
                  "host": "127.0.0.1", "port": port, "health_path": "/"})
        assert n["ok"]
        assert n["severity"] == "ok"
        assert n["probe_kind"] == "http"
    finally:
        srv.shutdown()


def test_http_probe_fail_for_5xx():
    srv = _serve(_Err500)
    try:
        port = srv.server_address[1]
        n = _run({"id": "x", "type": "service", "name": "x",
                  "host": "127.0.0.1", "port": port, "health_path": "/"})
        assert not n["ok"]
        assert n["severity"] == "fail"
        assert "500" in n["status"]["error"]
    finally:
        srv.shutdown()


def test_http_probe_fail_when_port_unbound():
    # Bind+close so we *know* the port is unbound.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    n = _run({"id": "x", "type": "service", "name": "x",
              "host": "127.0.0.1", "port": port, "health_path": "/health"})
    assert not n["ok"]
    assert n["severity"] == "fail"


# --- TCP probe -------------------------------------------------------------

def test_tcp_probe_ok_on_loopback():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        n = _run({"id": "x", "type": "service", "name": "x",
                  "host": "127.0.0.1", "port": port, "probe_kind": "tcp"})
        assert n["ok"]
        assert n["severity"] == "ok"
        assert n["probe_kind"] == "tcp"
    finally:
        srv.close()


def test_tcp_probe_fail_on_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    n = _run({"id": "x", "type": "service", "name": "x",
              "host": "127.0.0.1", "port": port, "probe_kind": "tcp"})
    assert not n["ok"]
    assert n["severity"] == "fail"


def test_tcp_probe_fail_on_timeout_to_unreachable():
    # RFC 5737 TEST-NET-1 — guaranteed non-routable.
    n = _run({"id": "x", "type": "service", "name": "x",
              "host": "192.0.2.1", "port": 9, "probe_kind": "tcp"})
    assert not n["ok"]
    assert n["severity"] == "fail"


# --- misconfigured entry ---------------------------------------------------

def test_unknown_when_no_probe_kind_set():
    n = _run({"id": "x", "type": "service", "name": "x",
              "host": "127.0.0.1", "port": 1})
    assert n["severity"] == "unknown"
    assert "no probe configured" in n["status"]["error"]
