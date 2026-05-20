"""Operator-facing controls for the EdgeNode (Teltonika RutOS router).

Same shape as services/ui/app/{apex,bsi,tak}/routes.py: one class,
FastAPI router as thin delegation.

  - state    Combined reachability + device identity + GPS fix.
             Logs into the router's REST API on demand (token cached
             until expiry), reads /api/system/device/status and
             /api/gps/position/status, returns one operator-friendly dict.

Auth credentials come from env (ROUTER_USER / ROUTER_PASSWORD), passed
in by docker-compose. The router admin UI sets X-Frame-Options:
SAMEORIGIN, so the panel uses a new-tab "Open Router UI ↗" link rather
than an iframe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import paramiko
from fastapi import APIRouter, HTTPException

from ..nodes import client as nodes_client

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

    def _api_get(self, host: str, path: str) -> dict | None:
        """Authenticated GET against the RutOS API. Returns the `data`
        field on success, None on auth failure (so callers gracefully
        degrade)."""
        for attempt in range(2):  # one retry on 401 with fresh login
            token = self._token_for(host)
            req = urllib.request.Request(
                f"{self._base_url(host)}{path}",
                headers={"Authorization": f"Bearer {token}"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.TIMEOUT,
                                            context=self._ssl_ctx) as resp:
                    payload = json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self._token = None
                    continue
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                return None
            # RutOS returns either {success, data, ...} or the raw data block
            if isinstance(payload, dict) and "success" in payload:
                if not payload.get("success"):
                    return None
                return payload.get("data")
            return payload
        return None

    # ------ SSH for UCI / NTP-toggle -------------------------------------

    def _ssh_run_sync(self, host: str, cmd: str, timeout: float = 5.0) -> tuple[int, str, str]:
        """Run cmd on the router over SSH as the admin user (password auth).
        Used for UCI calls — REST API on this firmware doesn't expose NTP."""
        user = os.environ.get("ROUTER_USER", "admin")
        pw   = os.environ.get("ROUTER_PASSWORD", "")
        if not pw:
            raise HTTPException(500, detail="ROUTER_PASSWORD env not set")
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            cli.connect(host, port=22, username=user, password=pw,
                        timeout=2.5, allow_agent=False, look_for_keys=False)
            _, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            rc  = stdout.channel.recv_exit_status()
            return rc, out, err
        finally:
            cli.close()

    async def _ssh_run(self, host: str, cmd: str) -> tuple[int, str, str]:
        return await asyncio.to_thread(self._ssh_run_sync, host, cmd)

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

    # ------ State -----------------------------------------------------------

    async def state(self) -> dict:
        n = await self._node()
        host = n.get("host", "192.168.201.1")
        try:
            device = self._api_get(host, "/api/system/device/status") or {}
            gps    = self._api_get(host, "/api/gps/position/status") or {}
        except HTTPException as exc:
            return {"available": False, "reason": str(exc.detail), "host": host}
        if not device and not gps:
            return {"available": False, "reason": "router API unreachable", "host": host}

        # The /device/status payload is wrapped; the /gps payload is flat.
        static = device.get("static", {}) if isinstance(device, dict) else {}
        mnf    = device.get("mnfinfo", {}) if isinstance(device, dict) else {}

        def _f(x: str | None) -> float | None:
            try:    return float(x) if x is not None else None
            except (TypeError, ValueError): return None

        # Direct SNTP probe — no longer depending on services/ntp. If it
        # responds, the router's NTP server is up. The offset_s lets us
        # render the router's view of "now" without a second round-trip.
        ntp = self._sntp_probe(host)
        ntp["server_enabled"] = bool(ntp.get("ok"))
        if ntp.get("ok") and ntp.get("offset_s") is not None:
            router_unix = time.time() + ntp["offset_s"]
            ntp["router_time_iso"] = (
                datetime.fromtimestamp(router_unix, tz=timezone.utc)
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z"))
        else:
            ntp["router_time_iso"] = None

        return self._state_payload(host, device, gps, ntp)

    def _state_payload(self, host, device, gps, ntp) -> dict:
        static = device.get("static", {}) if isinstance(device, dict) else {}
        mnf    = device.get("mnfinfo", {}) if isinstance(device, dict) else {}
        def _f(x):
            try:    return float(x) if x is not None else None
            except (TypeError, ValueError): return None
        return {
            "available":   True,
            "host":        host,
            "web_url":     self._base_url(host) + "/",
            "device": {
                "hostname":   static.get("hostname"),
                "model":      mnf.get("name"),
                "fw_version": static.get("fw_version"),
                "kernel":     static.get("kernel"),
                "serial":     mnf.get("serial"),
            },
            "gps": {
                "fix_status": gps.get("fix_status"),
                "satellites": int(gps.get("satellites") or 0),
                "latitude":   _f(gps.get("latitude")),
                "longitude":  _f(gps.get("longitude")),
                "altitude":   _f(gps.get("altitude")),
                "accuracy":   _f(gps.get("accuracy")),
            },
            "ntp": ntp,
        }

    # ------ NTP enable (UCI over SSH) --------------------------------------

    async def ntp_enable(self) -> dict:
        n = await self._node()
        host = n.get("host", "192.168.201.1")
        # RutOS NTP server lives under system.ntp on this firmware. Flip
        # enable_server, commit, kick sysntpd. One round-trip.
        cmd = ("uci set system.ntp.enable_server=1 && "
               "uci commit system && "
               "/etc/init.d/sysntpd restart")
        rc, out, err = await self._ssh_run(host, cmd)
        if rc != 0:
            raise HTTPException(
                500, detail=f"ntp_enable failed (rc={rc}): {err or out}")
        # Give sysntpd a moment to bind before probing.
        await asyncio.sleep(1.0)
        probe = self._sntp_probe(host)
        return {"enabled": True, "probe": probe}


router = APIRouter(prefix="/api/edge", tags=["edge"])
_ctrl = EdgeNodeController()


@router.get("/state")
async def state() -> dict:
    return await _ctrl.state()


@router.post("/ntp/enable")
async def ntp_enable() -> dict:
    return await _ctrl.ntp_enable()
