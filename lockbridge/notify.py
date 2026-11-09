"""Notifications: Web Push (PWA on phone), ntfy and Telegram."""

import asyncio
import base64
import json
import logging

import aiohttp

from . import config
from . import db as dbmod
from .events import bus

log = logging.getLogger("lockbridge.notify")

CATEGORIES = {
    "unlock": "Unlocking",
    "lock": "Locking",
    "door": "Door opened/closed",
    "battery": "Battery",
    "error": "Errors and availability",
    "security": "Security (logins, users)",
    "automation": "Automations",
}
DEFAULT_PREFS = {
    "unlock": True, "lock": False, "door": False, "battery": True,
    "error": True, "security": True, "automation": True, "own": False,
}
TITLES = {
    "unlock": "🔓 Unlocked",
    "lock": "🔒 Locked",
    "door": "🚪 Door",
    "battery": "🔋 Battery",
    "error": "⚠️ Warning",
    "security": "🛡️ Security",
    "automation": "⚙️ Automation",
}

_vapid = None
_public_key = ""


def init_vapid() -> None:
    global _vapid, _public_key
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01

    path = config.DATA_DIR / "vapid_private.pem"
    if not path.exists():
        v = Vapid01()
        v.generate_keys()
        v.save_key(str(path))
        path.chmod(0o600)
    _vapid = Vapid01.from_file(str(path))
    raw = _vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    _public_key = base64.urlsafe_b64encode(raw).decode().rstrip("=")


def public_key() -> str:
    return _public_key


def user_prefs(user: dict) -> dict:
    p = dict(DEFAULT_PREFS)
    try:
        p.update(json.loads(user.get("notify") or "{}"))
    except json.JSONDecodeError:
        pass
    if user.get("role") == "guest":
        p.update(security=False, battery=False, error=False, automation=False)
    elif user.get("role") != "admin":
        p["security"] = False
    return p


def _send_push_sync(sub: dict, payload: dict, contact: str) -> int:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=_vapid,
            vapid_claims={"sub": f"mailto:{contact}"},
            ttl=86400,
            timeout=15,
        )
        return 201
    except WebPushException as e:
        code = e.response.status_code if e.response is not None else 0
        log.warning("Web push failed (%s): %s", code, e)
        return code


async def push_to_user(user_id: int, payload: dict) -> int:
    from .lock import get_settings

    contact = get_settings()["contact_email"]
    subs = dbmod.db.all("SELECT * FROM push_subs WHERE user_id=?", (user_id,))
    sent = 0
    for s in subs:
        code = await asyncio.to_thread(_send_push_sync, json.loads(s["sub"]), payload, contact)
        if code in (404, 410):
            dbmod.db.execute("DELETE FROM push_subs WHERE id=?", (s["id"],))
        elif code < 300:
            sent += 1
    return sent


async def send(category: str, body: str, *, title: str | None = None, actor: str | None = None,
               tag: str | None = None) -> None:
    """Send a notification to everyone subscribed to the category."""
    title = title or TITLES.get(category, "LockBridge")
    payload = {"title": title, "body": body, "tag": tag or category, "url": "/#/logs", "category": category}
    for u in dbmod.db.all("SELECT * FROM users WHERE active=1"):
        prefs = user_prefs(u)
        if not prefs.get(category):
            continue
        if actor and not prefs.get("own") and actor == u["display_name"] and category in ("unlock", "lock"):
            continue
        await push_to_user(u["id"], payload)
    await _external(category, title, body)


async def _external(category: str, title: str, body: str) -> None:
    integ = dbmod.db.get("integrations", {}) or {}
    ntfy = integ.get("ntfy", {})
    tg = integ.get("telegram", {})
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        if ntfy.get("enabled") and ntfy.get("topic") and category in ntfy.get("categories", list(CATEGORIES)):
            headers = {"Authorization": f"Bearer {ntfy['token']}"} if ntfy.get("token") else {}
            msg = {
                "topic": ntfy["topic"], "title": title, "message": body, "tags": [category],
                "priority": 4 if category in ("error", "battery", "security") else 3,
            }
            try:
                await s.post(ntfy.get("server") or "https://ntfy.sh", json=msg, headers=headers)
            except Exception as e:  # noqa: BLE001
                log.warning("ntfy: %s", e)
        if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id") and category in tg.get("categories", list(CATEGORIES)):
            try:
                await s.post(
                    f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                    json={"chat_id": tg["chat_id"], "text": f"{title}\n{body}"},
                )
            except Exception as e:  # noqa: BLE001
                log.warning("telegram: %s", e)


async def _on_event(event: dict) -> None:
    cat = event.get("category")
    if cat not in CATEGORIES or cat == "automation":
        return  # automations send notifications explicitly with the "notify" action
    if event["type"] == "login":
        return
    await send(cat, event["message"], actor=event.get("user"), tag=event["type"])


def init() -> None:
    init_vapid()
    bus.subscribe(_on_event)
