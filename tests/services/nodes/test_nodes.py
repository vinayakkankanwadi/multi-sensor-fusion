"""nodes — health, CRUD, and per-type severity probes.

Three concerns in one file (one test_<service>.py per service convention):
  1. health
  2. CRUD (POST/PATCH/DELETE on /nodes)
  3. severity computation per node type (middleware, service, tak-server,
     platform-node). POST/PATCH/DELETE each force an immediate probe round
     so the next GET reflects the just-set config — no reliance on the
     NODES_INTERVAL_S poll cadence.
"""

from __future__ import annotations

import socket
import uuid


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    try:
        return s.getsockname()[1]
    finally:
        s.close()


def _open_listener() -> tuple[socket.socket, int]:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


# ---------- health -------------------------------------------------------

def test_health(http, nodes_url):
    r = http.get(f"{nodes_url}/health")
    assert r.status_code == 200


# ---------- POST ---------------------------------------------------------

def test_post_create_middleware(http, nodes_url, created_node):
    nid = created_node({
        "id": f"test-mw-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "test middleware",
        "host": "10.255.255.99", "port": 12345, "kind": "test",
    })
    r = http.get(f"{nodes_url}/nodes/{nid}")
    assert r.status_code == 200
    assert r.json()["id"] == nid


def test_post_rejects_duplicate_id(http, nodes_url, created_node):
    nid = created_node({
        "id": f"test-dup-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "first",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    r = http.post(f"{nodes_url}/nodes", json={
        "id": nid, "type": "middleware", "name": "dup",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    assert r.status_code == 409


def test_post_rejects_invalid_id(http, nodes_url):
    r = http.post(f"{nodes_url}/nodes", json={
        "id": "has spaces",
        "type": "middleware", "name": "x",
        "host": "h", "port": 1234, "kind": "x",
    })
    assert r.status_code in (400, 422)


def test_post_rejects_unknown_type(http, nodes_url):
    r = http.post(f"{nodes_url}/nodes", json={
        "id": f"test-bad-{uuid.uuid4().hex[:6]}",
        "type": "magic", "name": "x", "host": "h", "port": 1234,
    })
    assert r.status_code == 400
    assert "unknown type" in r.json().get("detail", "").lower()


def test_post_middleware_requires_port(http, nodes_url):
    r = http.post(f"{nodes_url}/nodes", json={
        "id": f"test-noport-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "x", "host": "h", "kind": "x",
    })
    assert r.status_code == 400
    assert "port" in r.json().get("detail", "").lower()


def test_post_service_requires_probe_config(http, nodes_url):
    r = http.post(f"{nodes_url}/nodes", json={
        "id": f"test-svc-{uuid.uuid4().hex[:6]}",
        "type": "service", "name": "x", "host": "h", "port": 8000,
    })
    assert r.status_code == 400
    assert "health_path" in r.json().get("detail", "").lower()


def test_post_platform_node_rejects_unknown_subservice(http, nodes_url):
    r = http.post(f"{nodes_url}/nodes", json={
        "id": f"test-pn-{uuid.uuid4().hex[:6]}",
        "type": "platform-node", "name": "x",
        "host": "10.0.0.1", "services": ["ntp", "gps", "magic"],
    })
    assert r.status_code == 400
    assert "magic" in r.json().get("detail", "").lower()


# ---------- DELETE -------------------------------------------------------

def test_delete_removes_entry(http, nodes_url):
    nid = f"test-del-{uuid.uuid4().hex[:6]}"
    r = http.post(f"{nodes_url}/nodes", json={
        "id": nid, "type": "middleware", "name": "to be deleted",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    assert r.status_code == 201
    r = http.delete(f"{nodes_url}/nodes/{nid}")
    assert r.status_code == 200
    r = http.get(f"{nodes_url}/nodes/{nid}")
    assert r.status_code == 404


def test_delete_unknown_404(http, nodes_url):
    r = http.delete(f"{nodes_url}/nodes/does-not-exist-xyz")
    assert r.status_code == 404


# ---------- PATCH --------------------------------------------------------

def test_patch_extends_to_extras(http, nodes_url, created_node):
    nid = created_node({
        "id": f"test-patch-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "before",
        "host": "10.255.255.99", "port": 12345, "kind": "before",
    })
    r = http.patch(f"{nodes_url}/nodes/{nid}", json={
        "name": "Renamed", "description": "now with details",
        "kind": "windows-bsi-harness", "probe": False,
    })
    assert r.status_code == 200, r.text
    after = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert after["name"] == "Renamed"
    assert after["description"] == "now with details"
    assert after["kind"] == "windows-bsi-harness"
    assert after["probe"] is False


def test_patch_strips_whitespace_on_host(http, nodes_url, created_node):
    nid = created_node({
        "id": f"test-ws-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "x",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    r = http.patch(f"{nodes_url}/nodes/{nid}", json={"host": "  10.1.1.1  "})
    assert r.status_code == 200
    after = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert after["host"] == "10.1.1.1"


def test_patch_empty_body_rejected(http, nodes_url, created_node):
    nid = created_node({
        "id": f"test-empty-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "x",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    r = http.patch(f"{nodes_url}/nodes/{nid}", json={})
    assert r.status_code == 400


def test_patch_unknown_404(http, nodes_url):
    r = http.patch(f"{nodes_url}/nodes/missing-xyz", json={"host": "x"})
    assert r.status_code == 404


def test_patch_id_and_type_cannot_be_changed(http, nodes_url, created_node):
    """id/type are immutable. PATCH model omits them, so a body of only
    those fields is effectively empty → 400."""
    nid = created_node({
        "id": f"test-imm-{uuid.uuid4().hex[:6]}",
        "type": "middleware", "name": "x",
        "host": "10.255.255.99", "port": 12345, "kind": "x",
    })
    r = http.patch(f"{nodes_url}/nodes/{nid}",
                   json={"id": "renamed", "type": "service"})
    assert r.status_code == 400
    after = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert after["id"] == nid
    assert after["type"] == "middleware"


# ---------- middleware probe ---------------------------------------------

def test_middleware_severity_ok_against_loopback_listener(http, nodes_url, created_node):
    srv, port = _open_listener()
    try:
        nid = created_node({
            "id": f"mw-ok-{uuid.uuid4().hex[:6]}", "type": "middleware",
            "name": "loopback listener", "host": "127.0.0.1", "port": port,
            "kind": "test",
        })
        n = http.get(f"{nodes_url}/nodes/{nid}").json()
        assert n["ok"] is True
        assert n["severity"] == "ok"
        assert n["status"]["rtt_s"] is not None
    finally:
        srv.close()


def test_middleware_severity_fail_on_refused_port(http, nodes_url, created_node):
    port = _free_port()
    nid = created_node({
        "id": f"mw-fail-{uuid.uuid4().hex[:6]}", "type": "middleware",
        "name": "closed port", "host": "127.0.0.1", "port": port,
        "kind": "test",
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["ok"] is False
    assert n["severity"] == "fail"


def test_middleware_probe_disabled_is_unknown(http, nodes_url, created_node):
    nid = created_node({
        "id": f"mw-noprobe-{uuid.uuid4().hex[:6]}", "type": "middleware",
        "name": "skipped", "host": "127.0.0.1", "port": 65500,
        "kind": "test", "probe": False,
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["severity"] == "unknown"
    assert "probing disabled" in n["status"]["error"].lower()


# ---------- service probe (HTTP / TCP) -----------------------------------

def test_service_http_probe_ok_against_running_ui(http, nodes_url, created_node):
    nid = created_node({
        "id": f"svc-ok-{uuid.uuid4().hex[:6]}", "type": "service",
        "name": "running ui", "host": "127.0.0.1", "port": 8080,
        "health_path": "/api/health",
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["ok"] is True
    assert n["severity"] == "ok"
    assert n["probe_kind"] == "http"


def test_service_http_probe_fail_when_port_unbound(http, nodes_url, created_node):
    port = _free_port()
    nid = created_node({
        "id": f"svc-fail-{uuid.uuid4().hex[:6]}", "type": "service",
        "name": "down", "host": "127.0.0.1", "port": port,
        "health_path": "/health",
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["ok"] is False
    assert n["severity"] == "fail"


def test_service_tcp_probe_ok_against_open_socket(http, nodes_url, created_node):
    srv, port = _open_listener()
    try:
        nid = created_node({
            "id": f"svc-tcp-{uuid.uuid4().hex[:6]}", "type": "service",
            "name": "tcp open", "host": "127.0.0.1", "port": port,
            "probe_kind": "tcp",
        })
        n = http.get(f"{nodes_url}/nodes/{nid}").json()
        assert n["ok"] is True
        assert n["severity"] == "ok"
        assert n["probe_kind"] == "tcp"
    finally:
        srv.close()


def test_service_tcp_probe_fail_on_refused(http, nodes_url, created_node):
    port = _free_port()
    nid = created_node({
        "id": f"svc-tcp-fail-{uuid.uuid4().hex[:6]}", "type": "service",
        "name": "tcp refused", "host": "127.0.0.1", "port": port,
        "probe_kind": "tcp",
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["ok"] is False
    assert n["severity"] == "fail"


# ---------- tak-server probe ---------------------------------------------

def test_tak_server_default_unknown(http, nodes_url, created_node):
    nid = created_node({
        "id": f"tak-{uuid.uuid4().hex[:6]}", "type": "tak-server",
        "name": "tak default", "host": "192.168.201.222", "port": 6969,
        "protocol": "udp",
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["severity"] == "unknown"
    assert n["ok"] is False
    assert n["probe_kind"] is None
    assert "udp" in n["status"]["error"].lower()


def test_tak_server_tcp_admin_probe_ok(http, nodes_url, created_node):
    srv, admin_port = _open_listener()
    try:
        nid = created_node({
            "id": f"tak-tcp-{uuid.uuid4().hex[:6]}", "type": "tak-server",
            "name": "tak admin tcp", "host": "127.0.0.1", "port": 6969,
            "probe_kind": "tcp", "admin_port": admin_port,
        })
        n = http.get(f"{nodes_url}/nodes/{nid}").json()
        assert n["ok"] is True
        assert n["severity"] == "ok"
        assert n["probe_kind"] == "tcp"
        assert n["admin_port"] == admin_port
    finally:
        srv.close()


def test_tak_server_tcp_admin_probe_fail_on_refused(http, nodes_url, created_node):
    admin_port = _free_port()
    nid = created_node({
        "id": f"tak-tcp-fail-{uuid.uuid4().hex[:6]}", "type": "tak-server",
        "name": "tak admin refused", "host": "127.0.0.1", "port": 6969,
        "probe_kind": "tcp", "admin_port": admin_port,
    })
    n = http.get(f"{nodes_url}/nodes/{nid}").json()
    assert n["ok"] is False
    assert n["severity"] == "fail"


# ---------- platform-node composition ------------------------------------

def test_platform_node_composes_ntp_and_gps(http, nodes_url):
    """The router (a platform-node) aggregates NTP + GPS into a single
    composed severity. Verify the /nodes/current view exposes both
    sub-service severities and a composed top-level severity."""
    http.post(f"{nodes_url}/nodes/refresh", timeout=10.0)
    items = http.get(f"{nodes_url}/nodes/current?type=platform-node").json()["nodes"]
    assert items, "no platform-node configured — expected at least 'router'"
    n = items[0]
    assert "services" in n
    assert "ntp" in n["services"]
    assert "gps" in n["services"]
    assert n["severity"] in ("ok", "warn", "fail", "unknown")
