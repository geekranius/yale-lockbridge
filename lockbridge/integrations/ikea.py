"""IKEA DIRIGERA hub – local REST/WebSocket API.

* Pairing: press the button on the back of the hub (OAuth PKCE flow, all local).
* Actions: turn lights and sockets on/off, start IKEA scenes.
* Triggers: presses on IKEA remotes/buttons (e.g. RODRET, SOMRIG, STYRBAR) can lock/unlock the door.
"""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import socket
import string
import time
from collections import deque

import aiohttp

from .. import db as dbmod

log = logging.getLogger("lockbridge.ikea")

PORT = 8443
DEFAULTS = {"enabled": False, "host": "", "token": ""}


def get_cfg() -> dict:
    c = dict(DEFAULTS)
    c.update((dbmod.db.get("integrations", {}) or {}).get("ikea", {}))
    return c


def save_cfg(**kw) -> None:
    integ = dbmod.db.get("integrations", {}) or {}
    integ.setdefault("ikea", {}).update(kw)
    dbmod.db.set("integrations", integ)


class IkeaClient:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self.status = "disabled"
        self.recent: deque = deque(maxlen=30)  # latest events from the hub (to make trigger setup easier)
        self._pair: dict | None = None

    def _base(self, host: str | None = None) -> str:
        return f"https://{host or get_cfg()['host']}:{PORT}/v1"

    def _session(self) -> aiohttp.ClientSession:
        # The hub uses a self-signed certificate on the local network
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=15)
        )

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {get_cfg()['token']}"}

    # ---------------- pairing ----------------
    async def pair_start(self, host: str) -> None:
        alphabet = string.ascii_letters + string.digits + "-._~"
        verifier = "".join(secrets.choice(alphabet) for _ in range(128))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        async with self._session() as s:
            async with s.get(
                f"{self._base(host)}/oauth/authorize",
                params={"audience": "homesmart.local", "response_type": "code",
                        "code_challenge": challenge, "code_challenge_method": "S256"},
            ) as r:
                if r.status != 200:
                    raise RuntimeError(f"Hub responded with HTTP {r.status}")
                code = (await r.json())["code"]
        self._pair = {"host": host, "code": code, "verifier": verifier, "ts": time.time()}

    async def pair_finish(self) -> bool:
        """Returns True once the button is pressed and the token is obtained."""
        p = self._pair
        if not p or time.time() - p["ts"] > 120:
            raise RuntimeError("Pairing timed out, start it again.")
        async with self._session() as s:
            async with s.post(
                f"{self._base(p['host'])}/oauth/token",
                data={"code": p["code"], "name": socket.gethostname() or "lockbridge",
                      "grant_type": "authorization_code", "code_verifier": p["verifier"]},
            ) as r:
                if r.status != 200:
                    return False
                token = (await r.json())["access_token"]
        save_cfg(host=p["host"], token=token, enabled=True)
        self._pair = None
        self.restart()
        return True

    # ---------------- REST ----------------
    async def _req(self, method: str, path: str, body=None):
        cfg = get_cfg()
        if not cfg["token"]:
            raise RuntimeError("IKEA hub is not paired")
        async with self._session() as s:
            async with s.request(method, self._base() + path, json=body, headers=self._auth()) as r:
                if r.status >= 400:
                    raise RuntimeError(f"IKEA hub: HTTP {r.status}")
                txt = await r.text()
                return json.loads(txt) if txt else None

    async def devices(self) -> list[dict]:
        out = []
        for d in await self._req("GET", "/devices") or []:
            a = d.get("attributes", {})
            out.append({
                "id": d["id"],
                "type": d.get("deviceType") or d.get("type"),
                "name": a.get("customName") or a.get("model") or d["id"],
                "room": (d.get("room") or {}).get("name"),
                "is_on": a.get("isOn"),
                "level": a.get("lightLevel"),
                "controllable": "isOn" in a,
            })
        return sorted(out, key=lambda d: (d["type"] or "", d["name"]))

    async def scenes(self) -> list[dict]:
        return [{"id": s["id"], "name": (s.get("info") or {}).get("name", s["id"])}
                for s in await self._req("GET", "/scenes") or []]

    async def set_device(self, device_id: str, on: bool, level=None):
        if not device_id:
            raise RuntimeError("No IKEA device selected")
        await self._req("PATCH", f"/devices/{device_id}", [{"attributes": {"isOn": bool(on)}}])
        if on and level:
            await self._req("PATCH", f"/devices/{device_id}", [{"attributes": {"lightLevel": int(level)}}])

    async def trigger_scene(self, scene_id: str):
        await self._req("POST", f"/scenes/{scene_id}/trigger")

    # ---------------- events (WebSocket) ----------------
    def restart(self):
        if self._task:
            self._task.cancel()
        cfg = get_cfg()
        if cfg["enabled"] and cfg["host"] and cfg["token"]:
            self._task = asyncio.create_task(self._ws_loop())
        else:
            self.status = "disabled" if not cfg["token"] else "paired, disabled"

    async def _ws_loop(self):
        from ..automations import engine

        while True:
            try:
                self.status = "connecting…"
                async with self._session() as s:
                    async with s.ws_connect(f"wss://{get_cfg()['host']}:{PORT}/v1", headers=self._auth(),
                                            heartbeat=30) as ws:
                        self.status = "connected"
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            ev = json.loads(msg.data)
                            data = ev.get("data") or {}
                            et = ev.get("type", "")
                            if et == "deviceStateChanged" and "isOn" not in (data.get("attributes") or {}) \
                                    and "remote" not in json.dumps(data).lower():
                                continue  # skip noise (sensors, temperature…)
                            summary = {
                                "time": time.strftime("%H:%M:%S"),
                                "type": et,
                                "device_id": data.get("id"),
                                "pattern": data.get("clickPattern") or (data.get("attributes") or {}).get("clickPattern"),
                                "button": data.get("buttonIndex"),
                            }
                            self.recent.appendleft(summary)
                            if "remotepress" in et.lower() or summary["pattern"]:
                                engine.fire_external("ikea", summary)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.status = f"error: {e}"
                log.warning("IKEA WS: %s", e)
                await asyncio.sleep(30)


client = IkeaClient()
