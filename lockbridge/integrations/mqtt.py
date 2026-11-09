"""MQTT + Home Assistant MQTT Discovery.

In Home Assistant the following appear automatically: the lock, battery, door (binary_sensor),
last event and availability. HA can then pass the lock on to Alexa, Google Home, Apple Home…
"""

import asyncio
import json
import logging

from .. import db as dbmod
from ..events import bus

log = logging.getLogger("lockbridge.mqtt")

DEFAULTS = {
    "enabled": False,
    "host": "",
    "port": 1883,
    "username": "",
    "password": "",
    "base_topic": "lockbridge",
    "discovery": True,
    "discovery_prefix": "homeassistant",
    "allow_unlock": True,
}


def get_cfg() -> dict:
    c = dict(DEFAULTS)
    c.update((dbmod.db.get("integrations", {}) or {}).get("mqtt", {}))
    return c


class MqttClient:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._client = None
        self.status = "disabled"

    def start(self):
        bus.subscribe(self._on_event)
        self.restart()

    def restart(self):
        if self._task:
            self._task.cancel()
        self._client = None
        cfg = get_cfg()
        if cfg["enabled"] and cfg["host"]:
            self._task = asyncio.create_task(self._run(cfg))
        else:
            self.status = "disabled"

    async def _run(self, cfg: dict):
        import aiomqtt

        from ..automations import engine
        from ..lock import manager

        base = cfg["base_topic"].strip("/") or "lockbridge"
        while True:
            try:
                self.status = "connecting…"
                async with aiomqtt.Client(
                    hostname=cfg["host"], port=int(cfg["port"]),
                    username=cfg["username"] or None, password=cfg["password"] or None,
                    identifier=f"lockbridge-{base}",
                    will=aiomqtt.Will(f"{base}/availability", "offline", retain=True),
                ) as client:
                    self._client = client
                    self.status = "connected"
                    await client.publish(f"{base}/availability", "online", retain=True)
                    if cfg["discovery"]:
                        await self._discovery(client, cfg, base)
                    await self.publish_state(manager.public_state())
                    await client.subscribe(f"{base}/lock/set")
                    await client.subscribe(f"{base}/refresh")
                    for t in engine.mqtt_topics():
                        await client.subscribe(t)
                    periodic = asyncio.create_task(self._periodic())
                    try:
                        await self._consume(client, cfg, base)
                    finally:
                        periodic.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._client = None
                self.status = f"error: {e}"
                log.warning("MQTT: %s – retrying in 20 s", e)
                await asyncio.sleep(20)

    async def _periodic(self):
        from ..lock import manager

        while True:
            await asyncio.sleep(60)
            await self.publish_state(manager.public_state())

    async def _consume(self, client, cfg: dict, base: str):
        from ..automations import engine
        from ..lock import manager

        async for msg in client.messages:
            topic = msg.topic.value
            payload = msg.payload.decode(errors="replace") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
            if topic == f"{base}/lock/set":
                asyncio.create_task(self._command(payload.strip().upper(), cfg))
            elif topic == f"{base}/refresh":
                await self.publish_state(manager.public_state())
            else:
                engine.fire_external("mqtt", {"topic": topic, "payload": payload})

    async def _command(self, payload: str, cfg: dict):
        from ..lock import LockError, manager

        action = {"LOCK": "lock", "UNLOCK": "unlock", "OPEN": "unlatch"}.get(payload)
        if not action:
            return
        if action != "lock" and not cfg["allow_unlock"]:
            bus.emit("error", "Unlocking over MQTT is disabled in settings.", level="warning", source="MQTT")
            return
        try:
            await manager.command(action, "Home Assistant", "MQTT")
        except LockError:
            pass  # already logged

    async def _discovery(self, client, cfg: dict, base: str):
        from .. import __version__
        from ..lock import get_settings, manager

        prefix = cfg["discovery_prefix"].strip("/")
        uid = base.replace("/", "_")
        info = manager.state.get("info") or {}
        device = {
            "identifiers": [uid],
            "name": get_settings()["site_name"],
            "manufacturer": "Yale (via LockBridge)",
            "model": info.get("model") or "Yale BLE",
            "sw_version": __version__,
        }
        avail = [{"topic": f"{base}/availability"}]
        entities = {
            f"{prefix}/lock/{uid}/lock/config": {
                "name": None, "unique_id": f"{uid}_lock", "command_topic": f"{base}/lock/set",
                "state_topic": f"{base}/lock/state", "payload_lock": "LOCK", "payload_unlock": "UNLOCK",
                "state_locked": "LOCKED", "state_unlocked": "UNLOCKED", "state_locking": "LOCKING",
                "state_unlocking": "UNLOCKING", "state_jammed": "JAMMED", "optimistic": False,
                **({"payload_open": "OPEN", "state_open": "UNLATCHED", "state_opening": "UNLATCHING"}
                   if manager.state.get("unlatch") else {}),
            },
            f"{prefix}/sensor/{uid}/battery/config": {
                "name": "Battery", "unique_id": f"{uid}_battery", "state_topic": f"{base}/battery",
                "device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement",
            },
            f"{prefix}/binary_sensor/{uid}/door/config": {
                "name": "Door", "unique_id": f"{uid}_door", "state_topic": f"{base}/door",
                "device_class": "door", "payload_on": "OPEN", "payload_off": "CLOSED",
            },
            f"{prefix}/sensor/{uid}/last_event/config": {
                "name": "Last event", "unique_id": f"{uid}_last_event", "state_topic": f"{base}/event",
                "value_template": "{{ value_json.message[:250] }}", "json_attributes_topic": f"{base}/event",
                "icon": "mdi:history",
            },
            f"{prefix}/sensor/{uid}/rssi/config": {
                "name": "Bluetooth signal", "unique_id": f"{uid}_rssi", "state_topic": f"{base}/rssi",
                "device_class": "signal_strength", "unit_of_measurement": "dBm", "entity_category": "diagnostic",
            },
        }
        for topic, conf in entities.items():
            conf.update(device=device, availability=avail)
            await client.publish(topic, json.dumps(conf), retain=True)

    async def publish_state(self, s: dict):
        if not self._client:
            return
        base = get_cfg()["base_topic"].strip("/") or "lockbridge"
        c = self._client
        try:
            await c.publish(f"{base}/lock/state", s["lock"], retain=True)
            door = {"OPENED": "OPEN", "AJAR": "OPEN", "CLOSED": "CLOSED"}.get(s["door"])
            if door:
                await c.publish(f"{base}/door", door, retain=True)
            if s.get("battery") is not None:
                await c.publish(f"{base}/battery", str(s["battery"]), retain=True)
            if s.get("rssi") is not None:
                await c.publish(f"{base}/rssi", str(s["rssi"]), retain=True)
            await c.publish(f"{base}/state", json.dumps({k: s[k] for k in ("lock", "door", "battery", "available", "last_actor")}), retain=True)
        except Exception as e:  # noqa: BLE001
            log.debug("publish_state: %s", e)

    async def publish_raw(self, topic: str, payload: str):
        if not self._client:
            raise RuntimeError("MQTT is not connected")
        await self._client.publish(topic, payload)

    async def _on_event(self, event: dict):
        if not self._client:
            return
        from ..lock import manager

        base = get_cfg()["base_topic"].strip("/") or "lockbridge"
        try:
            await self._client.publish(
                f"{base}/event",
                json.dumps({k: event.get(k) for k in ("ts", "type", "level", "message", "user", "source")}),
                retain=True,
            )
            await self.publish_state(manager.public_state())
        except Exception as e:  # noqa: BLE001
            log.debug("event publish: %s", e)


client = MqttClient()
