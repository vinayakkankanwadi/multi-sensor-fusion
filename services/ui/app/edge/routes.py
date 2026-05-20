"""Operator-facing controls for the EdgeNode (Teltonika RutOS router).

Same shape as services/ui/app/{apex,bsi,tak}/routes.py: one class,
FastAPI router as thin delegation. Everything is the router's own REST
API — `/api/date_time/ntp/{client,server}/config` for NTP and
`/api/gps/nmea/{config,rules/config}` + `/api/gps/position/status` for
GPS NMEA forwarding. Token-auth (login → bearer, ~299s expiry, cached).

We considered iframing the router's NTP / NMEA admin pages directly,
but they ship `X-Frame-Options: SAMEORIGIN` and the underlying SPA also
makes absolute-path XHRs to `/api/...`, so a same-origin reverse proxy
would also have to rewrite the SPA. Reading and writing the underlying
REST is the same data with none of the proxy moving parts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from ..nodes import client as nodes_client

# How fresh services/gps reception must be to count this box as actively
# receiving NMEA. The router pushes ~1 Hz; 8s leaves room for a few
# missed packets without flicker.
_RECEPTION_FRESH_S = 8.0

# Match "udp/0.0.0.0:8500 (from 192.168.201.1)" — services/gps's source string.
_GPS_SOURCE_RE = re.compile(r"from\s+(?P<ip>\d+\.\d+\.\d+\.\d+)")

# NTP epoch is 1900-01-01; Unix epoch is 1970-01-01.
_NTP_TO_UNIX = 2208988800
_NTP_PORT    = 123
_NTP_TIMEOUT = 1.5

log = logging.getLogger(__name__)


class EdgeNodeController:

    NODE_ID  = "router"
    TIMEOUT  = 2.5

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        # Self-signed router cert — we trust the LAN.
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ------ Node lookup ----------------------------------------------------

    async def _node(self) -> dict:
        payload = await nodes_client.fetch_current(type=None)
        for n in payload.get("nodes", []):
            if n.get("id") == self.NODE_ID:
                return n
        raise HTTPException(404, detail=f"node {self.NODE_ID!r} not found in registry")

    # ------ RutOS API helpers ----------------------------------------------

    def _base_url(self, host: str) -> str:
        return f"https://{host}"

    def _login(self, host: str) -> str:
        """Exchange admin user/password for a bearer token. Tokens last
        ~299s; we re-login when expired."""
        user = os.environ.get("ROUTER_USER", "admin")
        pw   = os.environ.get("ROUTER_PASSWORD", "")
        if not pw:
            raise HTTPException(500, detail="ROUTER_PASSWORD env not set")
        body = json.dumps({"username": user, "password": pw}).encode()
        req = urllib.request.Request(
            f"{self._base_url(host)}/api/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.TIMEOUT, context=self._ssl_ctx) as resp:
            data = json.loads(resp.read().decode())
        if not data.get("success"):
            raise HTTPException(500, detail=f"router login failed: {data}")
        tok = data["data"]["token"]
        exp = float(data["data"].get("expires", 60))
        self._token = tok
        # refresh 5 s before expiry to avoid races
        self._token_expires_at = time.time() + max(exp - 5.0, 10.0)
        return tok

    def _token_for(self, host: str) -> str:
        if not self._token or time.time() >= self._token_expires_at:
            return self._login(host)
        return self._token

    def _api_call(self, host: str, method: str, path: str,
                  body: dict | None = None) -> dict | None:
        """Authenticated request against the RutOS API. Returns the
        envelope's `data` field on success, None on auth/transport
        failure (so callers gracefully degrade)."""
        payload_bytes = json.dumps(body).encode() if body is not None else None
        for attempt in range(2):  # one retry on 401 with fresh login
            token = self._token_for(host)
            req = urllib.request.Request(
                f"{self._base_url(host)}{path}",
                data=payload_bytes,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=self.TIMEOUT,
                                            context=self._ssl_ctx) as resp:
                    raw = resp.read().decode()
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self._token = None
                    continue
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                return None
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return None
            if isinstance(payload, dict) and "success" in payload:
                if not payload.get("success"):
                    return None
                return payload.get("data")
            return payload
        return None

    def _api_get(self, host: str, path: str) -> dict | None:
        return self._api_call(host, "GET", path)

    def _api_put(self, host: str, path: str, data: dict) -> dict | None:
        return self._api_call(host, "PUT", path, {"data": data})

    # ------ Direct SNTP probe to the router --------------------------------

    @staticmethod
    def _sntp_probe(host: str, port: int = _NTP_PORT,
                    timeout_s: float = _NTP_TIMEOUT) -> dict:
        """Single NTP v3 client query to host:port. Returns offset/rtt and
        ok/severity flags. Direct UDP — no dependency on services/ntp."""
        # NTPv3 client packet: LI=0 (no leap), VN=3, Mode=3 (client). Rest 0.
        request = b"\x1b" + b"\x00" * 47
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout_s)
        t_send = time.time()
        try:
            sock.sendto(request, (host, port))
            data, _ = sock.recvfrom(1024)
            t_recv = time.time()
        except (socket.timeout, OSError) as exc:
            return {"ok": False, "severity": "fail", "error": str(exc),
                    "offset_s": None, "rtt_s": None}
        finally:
            sock.close()

        if len(data) < 48:
            return {"ok": False, "severity": "fail",
                    "error": f"short reply ({len(data)} bytes)",
                    "offset_s": None, "rtt_s": None}

        # Extract transmit timestamp (bytes 40-48, 64-bit fixed-point).
        sec, frac = struct.unpack("!II", data[40:48])
        server_unix = sec - _NTP_TO_UNIX + frac / (1 << 32)
        rtt = t_recv - t_send
        # Standard NTP offset estimator: server_time - (t_send + rtt/2)
        offset = server_unix - (t_send + rtt / 2)

        if abs(offset) > 2.0:    sev = "fail"
        elif abs(offset) > 0.5:  sev = "warn"
        else:                    sev = "ok"
        return {"ok": True, "severity": sev, "error": None,
                "offset_s": offset, "rtt_s": rtt}

    # ------ NTP + GPS REST snapshots --------------------------------------

    @staticmethod
    def _first(rows) -> dict:
        """RutOS list endpoints return [{...one entry...}]; pluck it or {}."""
        if isinstance(rows, list) and rows:
            return rows[0] if isinstance(rows[0], dict) else {}
        return rows if isinstance(rows, dict) else {}

    def _read_ntp(self, host: str) -> dict:
        client = self._first(self._api_get(host, "/api/date_time/ntp/client/config"))
        server = self._first(self._api_get(host, "/api/date_time/ntp/server/config"))
        # NTP upstream pool lives under /api/date_time/ntp/client/server/config
        # as a list of {hostname, id, ...}; failures fall back to [].
        srv_list = self._api_get(host, "/api/date_time/ntp/client/server/config") or []
        return {
            "client_enabled": client.get("enabled") == "1",
            "client_id":      client.get("id") or "ntpclient",
            "server_enabled": server.get("enabled") == "1",
            "server_id":      server.get("id") or "general",
            "zone_name":      client.get("zoneName"),
            "timezone":       client.get("timezone"),
            "servers": [s.get("hostname") for s in srv_list
                        if isinstance(s, dict) and s.get("hostname")],
        }

    def _read_gps(self, host: str) -> dict:
        fwd   = self._first(self._api_get(host, "/api/gps/nmea/config"))
        rules = self._api_get(host, "/api/gps/nmea/rules/config") or []
        pos   = self._api_get(host, "/api/gps/position/status") or {}

        # host_info entries are 'ip;port;proto' — normalise.
        targets = []
        for raw in fwd.get("host_info") or []:
            parts = (raw or "").split(";")
            targets.append({
                "host":  parts[0] if parts else None,
                "port":  int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                "proto": parts[2] if len(parts) > 2 else None,
            })

        def _f(x):
            try:    return float(x) if x is not None else None
            except (TypeError, ValueError): return None

        sentences_known     = [r.get("id") for r in rules if isinstance(r, dict)]
        sentences_forwarded = [r.get("id") for r in rules
                               if isinstance(r, dict) and r.get("forwarding_enabled") == "1"]

        return {
            "forwarding_enabled": fwd.get("enabled") == "1",
            "forwarding_id":      fwd.get("id") or "nmea_forwarding",
            "send_prefix":        fwd.get("send_prefix"),
            "targets":            targets,
            "sentences_known":     sentences_known,
            "sentences_forwarded": sentences_forwarded,
            "fix": {
                "fix_status": pos.get("fix_status"),
                "satellites": int(pos.get("satellites") or 0),
                "latitude":   _f(pos.get("latitude")),
                "longitude":  _f(pos.get("longitude")),
                "altitude":   _f(pos.get("altitude")),
                "accuracy":   _f(pos.get("accuracy")),
            },
        }

    # ------ State ----------------------------------------------------------

    async def state(self) -> dict:
        n = await self._node()
        host = n.get("host", "192.168.201.1")
        try:
            ntp_cfg, gps_cfg, sntp, recv, local_ips = await asyncio.gather(
                asyncio.to_thread(self._read_ntp,        host),
                asyncio.to_thread(self._read_gps,        host),
                asyncio.to_thread(self._sntp_probe,      host),
                asyncio.to_thread(self._read_reception),
                asyncio.to_thread(self._local_ipv4s),
            )
        except HTTPException as exc:
            return {"available": False, "reason": str(exc.detail), "host": host}

        if not ntp_cfg and not gps_cfg.get("fix"):
            return {"available": False, "reason": "router API unreachable", "host": host}

        ntp = dict(ntp_cfg)
        ntp["responding"]    = bool(sntp.get("ok"))
        ntp["sntp_severity"] = sntp.get("severity")
        ntp["sntp_error"]    = sntp.get("error")
        ntp["offset_s"]      = sntp.get("offset_s")
        ntp["rtt_s"]         = sntp.get("rtt_s")
        if sntp.get("ok") and sntp.get("offset_s") is not None:
            router_unix = time.time() + sntp["offset_s"]
            ntp["router_time_iso"] = (
                datetime.fromtimestamp(router_unix, tz=timezone.utc)
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"))
        else:
            ntp["router_time_iso"] = None

        gps = dict(gps_cfg)
        gps["local_ips"]        = local_ips
        gps["local_reception"]  = recv

        return {
            "available": True,
            "host":      host,
            "web_url":   self._base_url(host) + "/",
            "ntp":       ntp,
            "gps":       gps,
        }

    # ------ GPS reception / local IPs --------------------------------------

    @staticmethod
    def _local_ipv4s() -> list[str]:
        """All IPv4 addresses bound on this box. We run network_mode=host,
        so the ui container sees the host's interfaces. Loopback excluded.
        Used to decide whether a forwarding target is `us`."""
        try:
            hostname = socket.gethostname()
            ips = {info[4][0] for info in socket.getaddrinfo(hostname, None,
                                                              socket.AF_INET)}
        except (socket.gaierror, OSError):
            ips = set()
        # getaddrinfo can miss interface IPs; supplement with the
        # outbound-route trick (gets the IP the kernel would use for
        # any reachable target).
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.168.201.1", 80))
                ips.add(s.getsockname()[0])
        except OSError:
            pass
        return sorted(ip for ip in ips if not ip.startswith("127."))

    @staticmethod
    def _read_reception() -> dict:
        """Pull services/gps `/gps/current` and condense it to a
        per-receiver dict: are we actively getting NMEA, how recently,
        and from which sender."""
        gps_url = os.environ.get("GPS_URL", "http://127.0.0.1:8090").rstrip("/")
        try:
            with urllib.request.urlopen(f"{gps_url}/gps/current",
                                         timeout=2.0) as resp:
                cur = json.loads(resp.read().decode())
        except Exception:
            return {"receiving": False, "age_s": None, "sender": None}
        age = cur.get("age_s")
        sender = None
        m = _GPS_SOURCE_RE.search(cur.get("source") or "")
        if m:
            sender = m.group("ip")
        fresh = isinstance(age, (int, float)) and age <= _RECEPTION_FRESH_S
        return {
            "receiving": bool(cur.get("ok")) and fresh,
            "age_s":     age,
            "sender":    sender,
        }

    # ------ GPS forwarding hosts editor (REST PUT) -------------------------

    async def set_forwarding_hosts(self, hosts: list[dict]) -> dict:
        """Replace gps.nmea_forwarding.host_info with the operator's list.
        Each entry: {host, port, proto}. We round-trip read-then-PUT so
        the router keeps every other field unchanged."""
        n = await self._node()
        host = n.get("host", "192.168.201.1")
        cfg = await asyncio.to_thread(self._read_gps, host)
        # Serialise back to RutOS's "ip;port;proto" string format. Reject
        # entries that don't have all three — caller wants validation.
        host_info: list[str] = []
        for t in hosts:
            h = (t.get("host") or "").strip()
            p = t.get("port")
            proto = (t.get("proto") or "udp").strip().lower()
            if not h or not isinstance(p, int) or proto not in ("udp", "tcp"):
                raise HTTPException(
                    400, detail=f"invalid target {t!r}; need host/port(int)/proto in (udp,tcp)")
            host_info.append(f"{h};{p};{proto}")
        fwd_id = cfg.get("forwarding_id") or "nmea_forwarding"
        path = f"/api/gps/nmea/config/{fwd_id}"
        result = await asyncio.to_thread(
            self._api_put, host, path, {"host_info": host_info})
        if result is None:
            raise HTTPException(500, detail=f"PUT {path} host_info failed")
        # Immediate refresh, plus a delayed follow-up. Reason: if the
        # operator just removed our local IP, services/gps's age_s is
        # still ~0 right now — the probe would call it "ok" until the
        # freshness window closes. The delayed kick re-runs the probe
        # after the window has had time to expire, so the EdgeNode row
        # dot turns red without waiting for the 60 s poll.
        #
        # 200 ms before the first kick — the REST PUT response already
        # means the router applied the change to UCI; only the in-memory
        # NMEA forwarder needs a beat to re-read, so a long pause here
        # just adds dead time to every edit.
        await asyncio.sleep(0.2)
        await self._refresh_downstream()
        asyncio.create_task(self._delayed_refresh(9.0))
        return {"host_info": host_info, "result": result}

    @classmethod
    async def _delayed_refresh(cls, after_s: float) -> None:
        try:
            await asyncio.sleep(after_s)
            await cls._refresh_downstream()
        except Exception as exc:
            log.warning("delayed refresh failed: %s", exc)

    # ------ NTP toggles (REST PUT) -----------------------------------------

    async def _ntp_set(self, role: str, enable: bool) -> dict:
        """role ∈ {"client", "server"}. PUT the matching config row's
        `enabled` field — the router restarts ntpd internally. After
        the flip lands, kick services/ntp + services/nodes refresh so
        the EdgeNode row dot reflects new severity without waiting on
        their polling intervals."""
        n = await self._node()
        host = n.get("host", "192.168.201.1")
        cfg = await asyncio.to_thread(self._read_ntp, host)
        row_id = cfg["client_id"] if role == "client" else cfg["server_id"]
        path = f"/api/date_time/ntp/{role}/config/{row_id}"
        result = await asyncio.to_thread(
            self._api_put, host, path, {"enabled": "1" if enable else "0"})
        if result is None:
            raise HTTPException(
                500, detail=f"PUT {path} enabled={int(enable)} failed")
        # Router takes ~1s for ntpd to stop accepting queries after a
        # disable. Sleep before kicking probes so they see the new
        # reality.
        await asyncio.sleep(1.2)
        await self._refresh_downstream()
        return {"role": role, "enabled": enable,
                "probe": self._sntp_probe(host)}

    @staticmethod
    async def _refresh_downstream() -> None:
        """Best-effort: fire refreshes on services/ntp then services/nodes
        (order matters — nodes re-reads ntp). URLs come from the same
        NTP_URL / NODES_URL env we use for reads; defaults match the
        host-network compose layout. Errors logged, never raised."""
        ntp_url   = os.environ.get("NTP_URL",   "http://127.0.0.1:8091").rstrip("/")
        nodes_url = os.environ.get("NODES_URL", "http://127.0.0.1:8093").rstrip("/")
        for url in (f"{ntp_url}/ntp/refresh", f"{nodes_url}/nodes/refresh"):
            try:
                await asyncio.to_thread(
                    lambda u=url: urllib.request.urlopen(
                        urllib.request.Request(u, method="POST"),
                        timeout=5.0))
            except Exception as exc:
                log.warning("refresh kick failed %s: %s", url, exc)

    async def ntp_server_enable(self)  -> dict: return await self._ntp_set("server", True)
    async def ntp_server_disable(self) -> dict: return await self._ntp_set("server", False)
    async def ntp_client_enable(self)  -> dict: return await self._ntp_set("client", True)
    async def ntp_client_disable(self) -> dict: return await self._ntp_set("client", False)


router = APIRouter(prefix="/api/edge", tags=["edge"])
_ctrl = EdgeNodeController()


@router.get("/state")
async def state() -> dict:
    return await _ctrl.state()


@router.post("/ntp/server/enable")
async def ntp_server_enable() -> dict:
    return await _ctrl.ntp_server_enable()


@router.post("/ntp/server/disable")
async def ntp_server_disable() -> dict:
    return await _ctrl.ntp_server_disable()


@router.post("/ntp/client/enable")
async def ntp_client_enable() -> dict:
    return await _ctrl.ntp_client_enable()


@router.post("/ntp/client/disable")
async def ntp_client_disable() -> dict:
    return await _ctrl.ntp_client_disable()


@router.put("/gps/forwarding/hosts")
async def gps_forwarding_hosts(payload: dict = Body(...)) -> dict:
    """Replace the NMEA-forwarding host_info list. Body shape:
    `{"hosts": [{"host": "1.2.3.4", "port": 8500, "proto": "udp"}, ...]}`.
    A PUT of an empty list disables every target (router accepts that)."""
    hosts = payload.get("hosts")
    if not isinstance(hosts, list):
        raise HTTPException(400, detail="body must include 'hosts': list")
    return await _ctrl.set_forwarding_hosts(hosts)
