"""Passwords, TOTP 2FA, sessions, API tokens and login rate limiting."""

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime

import pyotp
import segno

from . import db as dbmod

SESSION_COOKIE = "lb_session"
SESSION_DAYS = 30
PENDING_SECONDS = 600

ROLES = ("admin", "user", "guest")


# ---------- passwords (scrypt, standard library) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 10:
        return "The password must be at least 10 characters long."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "The password must contain upper and lower case letters and at least one digit."
    return None


# ---------- TOTP ----------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str = "LockBridge") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(data: str, scale: int = 5) -> str:
    """QR code as inline SVG (with a viewBox so CSS can scale it without clipping)."""
    qr = segno.make(data, error="m")
    svg = qr.svg_inline(scale=scale, dark="#111", light="#fff", border=2)
    # segno does not write a viewBox, and CSS (.qr svg) sets a fixed size. Without a viewBox
    # the browser simply crops the content to that size (the QR code cannot be scanned) instead of scaling it.
    side = qr.symbol_size(scale=scale, border=2)[0]
    return svg.replace(
        "<svg ",
        f'<svg viewBox="0 0 {side} {side}" preserveAspectRatio="xMidYMid meet" '
        f'shape-rendering="crispEdges" ',
        1,
    )


def totp_qr_svg(uri: str) -> str:
    return qr_svg(uri)


def verify_totp(user_id: int, secret: str, code: str) -> bool:
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != 6 or not secret:
        return False
    totp = pyotp.TOTP(secret)
    now = time.time()
    db = dbmod.db
    last_step = db.get(f"totp_last:{user_id}", 0)
    for offset in (-1, 0, 1):
        t = now + offset * 30
        step = int(t // 30)
        if step <= last_step:
            continue  # protection against reuse of the same code
        if hmac.compare_digest(totp.at(t), code):
            db.set(f"totp_last:{user_id}", step)
            return True
    return False


# ---------- sessions ----------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int, stage: str, ip: str, ua: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    ttl = SESSION_DAYS * 86400 if stage == "full" else PENDING_SECONDS
    dbmod.db.execute(
        "INSERT INTO sessions(token_hash,user_id,stage,created_at,expires_at,ip,ua) VALUES(?,?,?,?,?,?,?)",
        (_hash_token(token), user_id, stage, now, now + ttl, ip, ua[:200]),
    )
    return token


def get_session(token: str | None) -> dict | None:
    if not token:
        return None
    row = dbmod.db.one("SELECT * FROM sessions WHERE token_hash=?", (_hash_token(token),))
    if not row:
        return None
    if row["expires_at"] < time.time():
        delete_session(token)
        return None
    return row


def delete_session(token: str) -> None:
    dbmod.db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def delete_user_sessions(user_id: int) -> None:
    dbmod.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def cleanup_sessions() -> None:
    dbmod.db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))


# ---------- API tokens (for Home Assistant, scripts, shortcuts) ----------
def create_api_token(name: str, role: str) -> str:
    token = "lb_" + secrets.token_urlsafe(32)
    dbmod.db.execute(
        "INSERT INTO api_tokens(name,token_hash,role,created_at) VALUES(?,?,?,?)",
        (name, _hash_token(token), role, time.time()),
    )
    return token


def check_api_token(token: str) -> dict | None:
    row = dbmod.db.one("SELECT * FROM api_tokens WHERE token_hash=?", (_hash_token(token),))
    if row:
        dbmod.db.execute("UPDATE api_tokens SET last_used=? WHERE id=?", (time.time(), row["id"]))
    return row


# ---------- rate limiting ----------
class RateLimiter:
    def __init__(self, max_failures: int = 8, window: int = 900):
        self.max_failures = max_failures
        self.window = window
        self.failures: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str) -> deque:
        q = self.failures[key]
        cutoff = time.time() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> bool:
        return any(len(self._trim(k)) >= self.max_failures for k in keys)

    def fail(self, *keys: str) -> None:
        for k in keys:
            self._trim(k).append(time.time())

    def reset(self, *keys: str) -> None:
        for k in keys:
            self.failures.pop(k, None)


login_limiter = RateLimiter()


# ---------- permissions ----------
def user_access_ok(user: dict) -> tuple[bool, str]:
    """Check whether the user is active and within the allowed period."""
    if not user.get("active"):
        return False, "The user account is disabled."
    now = datetime.now()
    try:
        if user.get("valid_from") and now < datetime.fromisoformat(user["valid_from"]):
            return False, "Access has not started yet."
        if user.get("valid_until") and now > datetime.fromisoformat(user["valid_until"]):
            return False, "Access has expired."
    except ValueError:
        pass
    return True, ""


def random_secret(nbytes: int = 18) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).decode().rstrip("=")
