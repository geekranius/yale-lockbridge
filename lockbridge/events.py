"""Event bus: logging to the activity log (SQLite) + distribution to subscribers (UI, automations, MQTT, notifications)."""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from . import db as dbmod

log = logging.getLogger("lockbridge.events")

# Categories for notifications
CATEGORY = {
    "unlocked": "unlock",
    "locked": "lock",
    "unlatched": "unlock",
    "door_opened": "door",
    "door_closed": "door",
    "door_ajar": "door",
    "battery_low": "battery",
    "battery_critical": "battery",
    "battery_ok": "battery",
    "jammed": "error",
    "error": "error",
    "lock_unavailable": "error",
    "lock_available": "error",
    "login_failed": "security",
    "login": "security",
    "user_changed": "security",
    "automation": "automation",
}

Listener = Callable[[dict], Awaitable[None] | None]


class EventBus:
    def __init__(self):
        self._listeners: list[Listener] = []
        self._sse_queues: set[asyncio.Queue] = set()

    def subscribe(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def sse_queue(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._sse_queues.add(q)
        return q

    def sse_close(self, q: asyncio.Queue) -> None:
        self._sse_queues.discard(q)

    def sse_close_all(self) -> None:
        """Close all SSE streams (e.g. on shutdown) so uvicorn does not wait for nothing."""
        for q in list(self._sse_queues):
            try:
                q.put_nowait(None)  # sentinel: the generator ends its loop
            except asyncio.QueueFull:
                pass
        self._sse_queues.clear()

    def broadcast(self, kind: str, payload: Any) -> None:
        """Send a message only to connected web clients (e.g. a status change)."""
        msg = {"kind": kind, "payload": payload}
        for q in list(self._sse_queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def emit(
        self,
        type: str,
        message: str,
        *,
        level: str = "info",
        source: str | None = None,
        user: str | None = None,
        data: dict | None = None,
        persist: bool = True,
    ) -> dict:
        event = {
            "ts": time.time(),
            "level": level,
            "type": type,
            "source": source,
            "user": user,
            "message": message,
            "data": data or {},
            "category": CATEGORY.get(type, "other"),
        }
        if persist and dbmod.db:
            cur = dbmod.db.execute(
                "INSERT INTO events(ts,level,type,source,user,message,data) VALUES(?,?,?,?,?,?,?)",
                (event["ts"], level, type, source, user, message, json.dumps(event["data"])),
            )
            event["id"] = cur.lastrowid
        log.log(logging.ERROR if level == "error" else logging.INFO, "[%s] %s", type, message)
        self.broadcast("event", event)
        for fn in self._listeners:
            try:
                res = fn(event)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(_guard(res))
            except Exception:  # noqa: BLE001
                log.exception("Listener failed")
        return event


async def _guard(coro):
    try:
        await coro
    except Exception:  # noqa: BLE001
        log.exception("Async listener failed")


bus = EventBus()
