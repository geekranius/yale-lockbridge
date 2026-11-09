"""A simple automation system: trigger → conditions → actions."""

import asyncio
import json
import logging
import time
from datetime import datetime

import aiohttp

from . import db as dbmod
from . import notify
from .events import bus
from .lock import DOOR_TEXT, LOCK_TEXT, manager

log = logging.getLogger("lockbridge.automations")

EVENT_TRIGGERS = {
    "unlocked": "Lock unlocked",
    "locked": "Lock locked",
    "unlatched": "Door opened (unlatch)",
    "door_opened": "Door opened",
    "door_closed": "Door closed",
    "jammed": "Lock jammed",
    "battery_low": "Low battery",
    "battery_critical": "Critical battery",
    "lock_unavailable": "Lock unavailable",
    "error": "Error",
    "login_failed": "Failed login",
}


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def load_all() -> list[dict]:
    rows = dbmod.db.all("SELECT * FROM automations ORDER BY id")
    for r in rows:
        r["enabled"] = bool(r["enabled"])
        for k in ("trigger", "conditions", "actions"):
            r[k] = json.loads(r[k])
    return rows


class Engine:
    def __init__(self):
        self._timers: dict[int, asyncio.Task] = {}
        self._runs: dict[int, list[float]] = {}
        self._clock_task: asyncio.Task | None = None
        self._last_minute = ""

    def start(self):
        bus.subscribe(self._on_event)
        self._clock_task = asyncio.create_task(self._clock())
        self.reevaluate_timers()

    # ---------------- triggers ----------------
    async def _on_event(self, event: dict):
        if event["type"] == "automation":
            return
        for a in load_all():
            t = a["trigger"]
            if a["enabled"] and t.get("type") == "event" and t.get("event") == event["type"]:
                asyncio.create_task(self.run(a, {"event": event}))
        if event["type"] in ("locked", "unlocked", "unlatched", "door_opened", "door_closed", "door_ajar"):
            self.reevaluate_timers()

    def _state_true(self, what: str) -> bool:
        s = manager.state
        if what == "unlocked":
            return s["lock"] in ("UNLOCKED", "UNLATCHED")
        if what == "door_open":
            return s["door"] in ("OPENED", "AJAR")
        if what == "door_closed_unlocked":
            return s["door"] == "CLOSED" and s["lock"] in ("UNLOCKED", "UNLATCHED")
        return False

    def reevaluate_timers(self):
        active_ids = set()
        for a in load_all():
            t = a["trigger"]
            if not a["enabled"] or t.get("type") != "state_for":
                continue
            active_ids.add(a["id"])
            if self._state_true(t.get("what", "")):
                if a["id"] not in self._timers:
                    self._timers[a["id"]] = asyncio.create_task(self._state_timer(a))
            elif task := self._timers.pop(a["id"], None):
                task.cancel()
        for aid in list(self._timers):
            if aid not in active_ids:
                self._timers.pop(aid).cancel()

    async def _state_timer(self, a: dict):
        try:
            await asyncio.sleep(max(5, float(a["trigger"].get("minutes", 1)) * 60))
            if self._state_true(a["trigger"].get("what", "")):
                await self.run(a, {})
        except asyncio.CancelledError:
            pass
        finally:
            if self._timers.get(a["id"]) is asyncio.current_task():
                self._timers.pop(a["id"], None)

    async def _clock(self):
        while True:
            now = datetime.now()
            minute = now.strftime("%Y-%m-%d %H:%M")
            if minute != self._last_minute:
                self._last_minute = minute
                hm = now.strftime("%H:%M")
                for a in load_all():
                    t = a["trigger"]
                    if a["enabled"] and t.get("type") == "time" and t.get("at") == hm:
                        days = t.get("days") or list(range(7))
                        if now.weekday() in days:
                            asyncio.create_task(self.run(a, {}))
            await asyncio.sleep(10)

    def fire_webhook(self, hook: str, payload: dict) -> int:
        n = 0
        for a in load_all():
            t = a["trigger"]
            if a["enabled"] and t.get("type") == "webhook" and t.get("hook") == hook:
                asyncio.create_task(self.run(a, {"payload": payload}))
                n += 1
        return n

    def fire_external(self, kind: str, data: dict) -> None:
        """Called by the IKEA and MQTT integrations."""
        for a in load_all():
            t = a["trigger"]
            if not a["enabled"] or t.get("type") != kind:
                continue
            if kind == "ikea":
                if t.get("device_id") and t["device_id"] != data.get("device_id"):
                    continue
                if t.get("pattern") and t["pattern"] != data.get("pattern"):
                    continue
            elif kind == "mqtt":
                if t.get("topic") != data.get("topic"):
                    continue
                if t.get("payload") and t["payload"] != data.get("payload"):
                    continue
            asyncio.create_task(self.run(a, {"payload": data}))

    def mqtt_topics(self) -> list[str]:
        return sorted({a["trigger"]["topic"] for a in load_all()
                       if a["enabled"] and a["trigger"].get("type") == "mqtt" and a["trigger"].get("topic")})

    # ---------------- conditions ----------------
    @staticmethod
    def _conditions_ok(conds: list[dict]) -> tuple[bool, str]:
        now = datetime.now()
        for c in conds or []:
            t = c.get("type")
            if t == "time_between":
                f, to, cur = c.get("from", "00:00"), c.get("to", "23:59"), now.strftime("%H:%M")
                inside = f <= cur <= to if f <= to else (cur >= f or cur <= to)
                if not inside:
                    return False, f"outside the time {f}–{to}"
            elif t == "weekday":
                if now.weekday() not in (c.get("days") or []):
                    return False, "day of week"
            elif t == "lock_is":
                if manager.state["lock"] != c.get("state"):
                    return False, "lock state"
            elif t == "door_not_open":
                if manager.state["door"] in ("OPENED", "AJAR"):
                    return False, "door is open"
            elif t == "door_is":
                if manager.state["door"] != c.get("state"):
                    return False, "door state"
        return True, ""

    # ---------------- actions ----------------
    async def run(self, a: dict, ctx: dict, *, manual_by: str | None = None) -> None:
        now = time.time()
        runs = [t for t in self._runs.get(a["id"], []) if now - t < 60]
        if len(runs) >= 10:
            bus.emit("error", f"Automation '{a['name']}' stopped – too many runs (loop?).", level="error",
                     source="automation")
            return
        runs.append(now)
        self._runs[a["id"]] = runs

        if not manual_by:
            ok, why = self._conditions_ok(a.get("conditions"))
            if not ok:
                log.info("Automation %s skipped: %s", a["name"], why)
                return
        dbmod.db.execute("UPDATE automations SET last_run=? WHERE id=?", (now, a["id"]))
        ev = ctx.get("event") or {}
        st = manager.state
        vars_ = _SafeDict(
            name=a["name"], user=ev.get("user") or "unknown", message=ev.get("message", ""),
            battery=st.get("battery") if st.get("battery") is not None else "?",
            lock=LOCK_TEXT.get(st["lock"], st["lock"]), door=DOOR_TEXT.get(st["door"], st["door"]),
            time=datetime.now().strftime("%H:%M"), date=datetime.now().strftime("%d.%m.%Y."),
        )
        actor = f"Automation: {a['name']}"
        done = []
        try:
            for act in a.get("actions", []):
                t = act.get("type")
                if t in ("lock", "unlock", "unlatch"):
                    await manager.command(t, actor, "automation")
                elif t == "notify":
                    await notify.send("automation", act.get("message", "").format_map(vars_) or a["name"],
                                      title=act.get("title") or None)
                elif t == "delay":
                    await asyncio.sleep(min(3600, float(act.get("seconds", 1))))
                elif t == "webhook":
                    body = (act.get("body") or "").format_map(vars_)
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                        async with s.request(act.get("method", "POST"), act["url"],
                                             data=body.encode() if body else None,
                                             headers={"Content-Type": act.get("content_type", "application/json")}) as r:
                            if r.status >= 400:
                                raise RuntimeError(f"webhook HTTP {r.status}")
                elif t == "mqtt":
                    from .integrations import mqtt

                    await mqtt.client.publish_raw(act["topic"], act.get("payload", "").format_map(vars_))
                elif t == "ikea_light":
                    from .integrations import ikea

                    await ikea.client.set_device(act["device_id"], act.get("on", True), act.get("level"))
                elif t == "ikea_scene":
                    from .integrations import ikea

                    await ikea.client.trigger_scene(act["scene_id"])
                done.append(t)
            bus.emit("automation", f"Automation '{a['name']}' executed" + (f" (started by {manual_by})" if manual_by else ""),
                     source="automation", user=manual_by, data={"automation": a["id"], "actions": done})
        except Exception as e:  # noqa: BLE001
            log.exception("automation")
            bus.emit("error", f"Automation '{a['name']}' failed: {e}", level="error", source="automation",
                     data={"automation": a["id"]})


engine = Engine()

TEMPLATES = [
    {
        "name": "Auto-lock after 2 min",
        "trigger": {"type": "state_for", "what": "unlocked", "minutes": 2},
        "conditions": [{"type": "door_not_open"}],
        "actions": [{"type": "lock"}],
    },
    {
        "name": "Warn if the door is open for 5 min",
        "trigger": {"type": "state_for", "what": "door_open", "minutes": 5},
        "conditions": [],
        "actions": [{"type": "notify", "message": "The door has been open for 5 minutes!"}],
    },
    {
        "name": "Nightly lock at 23:00",
        "trigger": {"type": "time", "at": "23:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "conditions": [{"type": "lock_is", "state": "UNLOCKED"}],
        "actions": [{"type": "lock"}, {"type": "notify", "message": "The door was locked automatically at {time}."}],
    },
    {
        "name": "Turn on the hallway light when unlocked in the evening",
        "trigger": {"type": "event", "event": "unlocked"},
        "conditions": [{"type": "time_between", "from": "18:00", "to": "06:00"}],
        "actions": [{"type": "ikea_light", "device_id": "", "on": True, "level": 80}],
    },
]
