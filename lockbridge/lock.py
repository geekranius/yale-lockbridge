"""Lock control over Bluetooth (yalexs-ble) – a replacement for the Yale Connect bridge.

The Raspberry Pi continuously scans for BLE advertisements and forwards them to the PushLock object,
which connects to the lock when needed (locally, encrypted with the offline key), reads the state and
executes commands.
"""

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Any

from . import config
from . import db as dbmod
from . import secret
from .events import bus

log = logging.getLogger("lockbridge.lock")

COMMAND_TIMEOUT = 45
UNAVAILABLE_AFTER = 600  # s without a BLE advertisement → lock unavailable
ATTRIBUTION_WINDOW = 60

LOCK_TEXT = {
    "LOCKED": "locked",
    "UNLOCKED": "unlocked",
    "LOCKING": "locking",
    "UNLOCKING": "unlocking",
    "UNLATCHED": "open (latch retracted)",
    "UNLATCHING": "opening",
    "JAMMED": "jammed",
    "SECUREMODE": "secure mode",
    "UNKNOWN": "unknown",
}
DOOR_TEXT = {"OPENED": "open", "CLOSED": "closed", "AJAR": "ajar", "UNKNOWN": "unknown"}
SOURCE_TEXT = {
    "MANUAL": "manual (key, handle or button on the lock)",
    "PIN": "keypad / PIN",
    "AUTO_LOCK": "automatic lock locking",
    "REMOTE": "remote (Yale Home app or another Bluetooth device)",
    "UNKNOWN": "unknown source",
}


class LockError(Exception):
    pass


def _name(v: Any) -> str:
    return getattr(v, "name", None) or (str(v) if v is not None else "UNKNOWN")


def default_settings() -> dict:
    return {
        "site_name": "Front door",
        "battery_warn": 25,
        "battery_critical": 10,
        "contact_email": "admin@lockbridge.local",
        "log_keep_days": 365,
        "unlock_confirm": True,
    }


def get_settings() -> dict:
    s = default_settings()
    s.update(dbmod.db.get("settings", {}) or {})
    return s


# ------------------------------------------------------------------ simulation
class SimulatedLock:
    """Fake lock for LB_DEMO=1 – the same interface as yalexs_ble.PushLock."""

    def __init__(self):
        self._cbs, self._acbs = [], []
        self.lock_status = "LOCKED"
        self.door = "CLOSED"
        self.battery = 64

    def register_callback(self, cb):
        self._cbs.append(cb)
        return lambda: self._cbs.remove(cb)

    def register_activity_callback(self, cb):
        self._acbs.append(cb)
        return lambda: self._acbs.remove(cb)

    def _push(self):
        from types import SimpleNamespace as NS

        state = NS(
            lock=NS(name=self.lock_status),
            door=NS(name=self.door),
            battery=NS(percentage=self.battery, voltage=round(4.6 + self.battery / 100 * 1.4, 2)),
        )
        info = NS(manufacturer="Yale", model="Linus L2 (DEMO)", serial="DEMO-0001", firmware="1.0.0")
        conn = NS(rssi=random.randint(-75, -55))
        for cb in list(self._cbs):
            cb(state, info, conn)

    async def start(self):
        await asyncio.sleep(0.5)
        self._push()
        return lambda: None

    async def _op(self, mid: str, end: str):
        self.lock_status = mid
        self._push()
        await asyncio.sleep(1.5)
        self.lock_status = end
        self._push()

    async def lock(self):
        await self._op("LOCKING", "LOCKED")

    async def unlock(self):
        await self._op("UNLOCKING", "UNLOCKED")
        asyncio.create_task(self._door_cycle())

    async def unlatch(self):
        await self._op("UNLATCHING", "UNLATCHED")
        asyncio.create_task(self._door_cycle())

    async def _door_cycle(self):
        await asyncio.sleep(3)
        self.door = "OPENED"
        self._push()
        await asyncio.sleep(6)
        self.door = "CLOSED"
        self._push()

    async def update(self):
        self._push()


# ------------------------------------------------------------------ manager
class LockManager:
    def __init__(self):
        self.push_lock = None
        self._cancel_start = None
        self._unsubs: list = []
        self._scanner = None
        self._scanner_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self.seen: dict[str, dict] = {}  # address → data about the discovered device
        self.state: dict = self._empty_state()
        self._pending: dict | None = None  # last command (for attributing it to a user)
        self._last_lock_event: dict | None = None
        self._last_adv = 0.0
        self._available = None
        self._busy = False

    def _empty_state(self) -> dict:
        return {
            "configured": False,
            "demo": config.DEMO,
            "available": False,
            "lock": "UNKNOWN",
            "door": "UNKNOWN",
            "battery": None,
            "voltage": None,
            "rssi": None,
            "info": None,
            "last_update": None,
            "last_change": None,
            "last_actor": None,
            "busy": False,
            "unlatch": False,
            "scanner": "stopped",
        }

    # ---------------- configuration ----------------
    @staticmethod
    def get_cfg() -> dict:
        raw = dict(dbmod.db.get("lock", {}) or {})
        key = raw.pop("key", None)
        if key:  # migration: older versions stored the key in the database
            secret.save_key(key)
            dbmod.db.set("lock", raw)
        cfg = dict(raw)
        if key := (key or secret.load_key()):
            cfg["key"] = key
        return cfg

    def is_configured(self) -> bool:
        cfg = self.get_cfg()
        return config.DEMO or bool(cfg.get("address") and cfg.get("key") and cfg.get("slot") is not None)

    def public_state(self) -> dict:
        s = dict(self.state)
        settings = get_settings()
        s["name"] = settings["site_name"]
        s["unlock_confirm"] = settings["unlock_confirm"]
        s["lock_text"] = LOCK_TEXT.get(s["lock"], s["lock"].lower())
        s["door_text"] = DOOR_TEXT.get(s["door"], s["door"].lower())
        return s

    def _changed(self):
        self.state["busy"] = self._busy
        bus.broadcast("status", self.public_state())

    # ---------------- lifecycle ----------------
    async def start(self):
        cfg = self.get_cfg()
        scanner = self.state.get("scanner", "stopped")
        self.state = self._empty_state()
        self.state["scanner"] = scanner
        self._available = None
        self.state["unlatch"] = bool(cfg.get("unlatch"))
        if not config.DEMO:
            await self._start_scanner()
        if not self.is_configured():
            self._changed()
            return
        self.state["configured"] = True
        try:
            if config.DEMO:
                self.push_lock = SimulatedLock()
            else:
                from yalexs_ble import PushLock

                self.push_lock = PushLock(
                    local_name=cfg.get("local_name") or None,
                    address=cfg["address"],
                    key=cfg["key"],
                    key_index=int(cfg["slot"]),
                    always_connected=bool(cfg.get("always_connected", False)),
                )
                if cfg.get("name"):
                    self.push_lock.set_name(cfg["name"])
                # if the device has already been seen, hand it over right away
                if dev := self.seen.get(cfg["address"].upper()):
                    if dev.get("_device") is not None:
                        self.push_lock.update_advertisement(dev["_device"], dev["_adv"])
            self._unsubs.append(self.push_lock.register_callback(self._on_state))
            self._unsubs.append(self.push_lock.register_activity_callback(self._on_activity))
            self._cancel_start = await self.push_lock.start()
        except Exception as e:  # noqa: BLE001
            log.exception("Starting the lock failed")
            bus.emit("error", f"Starting the connection to the lock failed: {e}", level="error", source="system")
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog())
        self._changed()

    async def stop(self):
        for u in self._unsubs:
            try:
                u()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        if self._cancel_start:
            try:
                self._cancel_start()
            except Exception:  # noqa: BLE001
                pass
            self._cancel_start = None
        self.push_lock = None

    async def restart(self):
        await self.stop()
        await self.start()

    async def shutdown(self):
        t0 = time.monotonic()
        tasks = [t for t in (self._scanner_task, self._watchdog_task) if t]
        await self.stop()
        for t in tasks:
            t.cancel()
        # BlueZ can block BleakScanner.stop() while a connection is active, so we limit
        # the wait – otherwise systemd waits 90 s and eventually kills the process with SIGKILL.
        if self._scanner:
            try:
                await asyncio.wait_for(self._scanner.stop(), 3)
            except Exception:  # noqa: BLE001
                log.warning("Bluetooth scanner did not stop within 3 s – continuing with shutdown")
            self._scanner = None
        log.info("Shutdown: scanner stopped in %.2fs", time.monotonic() - t0)
        self._scanner_task = None
        self._watchdog_task = None
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
            except Exception:  # noqa: BLE001
                pass
        log.info("Shutdown completed in %.2fs", time.monotonic() - t0)

    # ---------------- BLE scanner ----------------
    async def _start_scanner(self):
        if self._scanner_task is None:
            self._scanner_task = asyncio.create_task(self._scanner_loop())

    async def _scanner_loop(self):
        from bleak import BleakScanner

        while True:
            adapter = self.get_cfg().get("adapter") or None
            try:
                kwargs = {"detection_callback": self._on_adv, "scanning_mode": "active"}
                if adapter:
                    kwargs["adapter"] = adapter
                self._scanner = BleakScanner(**kwargs)
                await self._scanner.start()
                self.state["scanner"] = "running"
                self._changed()
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.state["scanner"] = f"error: {e}"
                self._changed()
                bus.emit(
                    "error",
                    f"Bluetooth scanner is not working ({e}). Check the Bluetooth adapter. Retrying in 30 s.",
                    level="error",
                    source="system",
                )
                await asyncio.sleep(30)

    def _on_adv(self, device, adv):
        from yalexs_ble.const import COMMAND_SERVICE_UUID, YALE_MFR_IDS

        addr = device.address.upper()
        mfr = set(adv.manufacturer_data.keys())
        is_yale = bool(mfr & set(YALE_MFR_IDS)) or COMMAND_SERVICE_UUID in [u.lower() for u in adv.service_uuids]
        cfg_addr = (self.get_cfg().get("address") or "").upper()
        if is_yale or addr == cfg_addr:
            self.seen[addr] = {
                "address": addr,
                "local_name": adv.local_name or device.name,
                "rssi": adv.rssi,
                "is_yale": is_yale,
                "last_seen": time.time(),
                "_device": device,
                "_adv": adv,
            }
        if addr == cfg_addr and self.push_lock is not None:
            self._last_adv = time.time()
            self.state["rssi"] = adv.rssi
            try:
                self.push_lock.update_advertisement(device, adv)
            except Exception:  # noqa: BLE001
                log.exception("update_advertisement")

    async def scan(self, seconds: float = 10) -> list[dict]:
        if config.DEMO:
            await asyncio.sleep(1)
            return [{"address": "AA:BB:CC:DD:EE:FF", "local_name": "L2DEMO01", "rssi": -61, "is_yale": True}]
        await self._start_scanner()
        start = time.time()
        await asyncio.sleep(seconds)
        out = [
            {k: v for k, v in d.items() if not k.startswith("_")}
            for d in self.seen.values()
            if d["last_seen"] >= start - 60
        ]
        return sorted(out, key=lambda d: (not d["is_yale"], -(d["rssi"] or -999)))

    # ---------------- lock callbacks ----------------
    def _on_state(self, state, info, conn):
        now = time.time()
        new_lock = _name(state.lock)
        new_door = _name(state.door)
        old_lock, old_door = self.state["lock"], self.state["door"]
        self.state["last_update"] = now
        self._last_adv = max(self._last_adv, now)
        if conn is not None and getattr(conn, "rssi", None) is not None:
            self.state["rssi"] = conn.rssi
        if info is not None:
            self.state["info"] = {
                "manufacturer": info.manufacturer,
                "model": info.model,
                "serial": info.serial,
                "firmware": info.firmware,
            }
        if state.battery is not None:
            self.state["battery"] = int(state.battery.percentage)
            self.state["voltage"] = state.battery.voltage
            self._check_battery()
        self.state["lock"] = new_lock
        self.state["door"] = new_door
        self._set_available(True)

        if old_lock != new_lock and old_lock != "UNKNOWN" or (old_lock == "UNKNOWN" and new_lock == "JAMMED"):
            self.state["last_change"] = now
            self._lock_event(new_lock)
        if old_door != new_door and old_door != "UNKNOWN" and new_door != "UNKNOWN":
            t = {"OPENED": "door_opened", "CLOSED": "door_closed", "AJAR": "door_ajar"}.get(new_door)
            if t:
                bus.emit(t, f"The door is {DOOR_TEXT[new_door]}.", source="lock", data={"door": new_door})
        self._changed()

    def _lock_event(self, new_lock: str):
        type_ = {"LOCKED": "locked", "UNLOCKED": "unlocked", "UNLATCHED": "unlatched", "JAMMED": "jammed"}.get(new_lock)
        if not type_:
            return  # intermediate states (LOCKING/UNLOCKING) are not recorded
        user, source = None, "lock"
        p = self._pending
        if p and time.time() - p["ts"] < ATTRIBUTION_WINDOW and (
            (p["action"] == "lock" and new_lock == "LOCKED")
            or (p["action"] in ("unlock", "unlatch") and new_lock in ("UNLOCKED", "UNLATCHED"))
        ):
            user, source = p["user"], p["source"]
            self._pending = None
        if type_ == "jammed":
            msg = "The lock is jammed! Check the door and the deadbolt."
            level = "error"
        else:
            verb = {"locked": "Locked", "unlocked": "Unlocked", "unlatched": "Door opened (unlatch)"}[type_]
            msg = f"{verb} – {user} ({source})" if user else f"{verb} – {SOURCE_TEXT['UNKNOWN']}"
            level = "info"
        self.state["last_actor"] = user or "unknown"
        ev = bus.emit(type_, msg, level=level, source=source, user=user, data={"lock": new_lock})
        self._last_lock_event = {**ev, "attributed": bool(user)}

    def _on_activity(self, activity):
        """Record from the lock's history – fills in the source (manual / PIN / auto-lock)."""
        status = _name(getattr(activity, "status", None))
        src = _name(getattr(activity, "source", None))
        if status in DOOR_TEXT:
            return
        ev = self._last_lock_event
        if not ev or ev.get("attributed") or time.time() - ev["ts"] > 90:
            return
        if src == "REMOTE":
            return  # no more information than what is already written
        txt = SOURCE_TEXT.get(src, src)
        slot = getattr(activity, "slot", None)
        if src == "PIN" and slot is not None:
            txt += f" (user #{slot})"
        verb = {"locked": "Locked", "unlocked": "Unlocked", "unlatched": "Door opened"}.get(ev["type"], ev["type"])
        msg = f"{verb} – {txt}"
        dbmod.db.execute("UPDATE events SET message=?, source=? WHERE id=?", (msg, txt, ev.get("id")))
        ev.update(message=msg, source=txt, attributed=True)
        self.state["last_actor"] = txt
        bus.broadcast("event_update", ev)
        self._changed()

    def _check_battery(self):
        s = get_settings()
        pct = self.state["battery"]
        level = dbmod.db.get("battery_alert_level", "ok")
        if pct <= s["battery_critical"] and level != "critical":
            dbmod.db.set("battery_alert_level", "critical")
            bus.emit("battery_critical", f"CRITICAL: lock battery is at {pct}%! Replace the batteries as soon as possible.",
                     level="error", source="lock", data={"battery": pct})
        elif s["battery_critical"] < pct <= s["battery_warn"] and level == "ok":
            dbmod.db.set("battery_alert_level", "low")
            bus.emit("battery_low", f"Lock battery is low ({pct}%). Replace the batteries soon.",
                     level="warning", source="lock", data={"battery": pct})
        elif pct > s["battery_warn"] + 5 and level != "ok":
            dbmod.db.set("battery_alert_level", "ok")
            bus.emit("battery_ok", f"Battery is OK ({pct}%).", source="lock", data={"battery": pct})

    def _set_available(self, avail: bool):
        if self._available is avail:
            return
        prev = self._available
        self._available = avail
        self.state["available"] = avail
        if prev is None and avail:
            return
        if avail:
            bus.emit("lock_available", "Connection to the lock re-established.", source="system")
        else:
            bus.emit("lock_unavailable", "The lock is unavailable (no Bluetooth signal). Check the distance and the batteries.",
                     level="error", source="system")

    async def _watchdog(self):
        while True:
            await asyncio.sleep(30)
            if config.DEMO or not self.state["configured"]:
                continue
            last = max(self._last_adv, self.state["last_update"] or 0)
            if last and time.time() - last > UNAVAILABLE_AFTER:
                self._set_available(False)
                self._changed()

    # ---------------- commands ----------------
    async def command(self, action: str, user: str, source: str) -> None:
        if action not in ("lock", "unlock", "unlatch"):
            raise LockError("Unknown command.")
        if not self.push_lock:
            raise LockError("The lock is not configured.")
        if action == "unlatch" and not self.state.get("unlatch"):
            raise LockError("Unlatching is not enabled for this lock.")
        if self._busy:
            raise LockError("The lock is currently executing another command, please wait a moment.")
        if not config.DEMO and getattr(self.push_lock, "ble_device", None) is None:
            raise LockError("The lock has not been found over Bluetooth yet. Check the distance from the Pi and the lock batteries.")
        self._busy = True
        self._pending = {"action": action, "user": user, "source": source, "ts": time.time()}
        self._changed()
        try:
            await asyncio.wait_for(getattr(self.push_lock, action)(), COMMAND_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            self._pending = None
            name = type(e).__name__
            if name == "AuthError":
                reason = "the lock rejected the key (invalid offline key or slot)"
            elif isinstance(e, (asyncio.TimeoutError, TimeoutError)):
                reason = "the lock did not respond in time"
            else:
                reason = str(e) or name
            what = {"lock": "Locking", "unlock": "Unlocking", "unlatch": "Opening"}[action]
            bus.emit("error", f"{what} failed ({user}, {source}): {reason}", level="error",
                     source=source, user=user, data={"action": action})
            raise LockError(f"{what} failed: {reason}") from e
        finally:
            self._busy = False
            self._changed()

    async def refresh(self):
        if self.push_lock:
            await self.push_lock.update()


manager = LockManager()


def fmt_ts(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y. %H:%M:%S") if ts else "-"
