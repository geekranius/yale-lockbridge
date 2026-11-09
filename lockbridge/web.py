"""FastAPI web server: REST API + PWA interface."""

import asyncio
import csv
import io
import json
import logging
import os
import platform
import shutil
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config
from . import db as dbmod
from . import cfaccess, notify, secret, security
from .automations import EVENT_TRIGGERS, TEMPLATES, engine, load_all
from .cloud import CloudLogin, parse_ha_config_entries, validate_key
from .events import bus
from .integrations import alexa, ikea, mqtt
from .lock import LockError, default_settings, get_settings, manager

log = logging.getLogger("lockbridge.web")
STARTED = time.time()
RANK = {"guest": 0, "user": 1, "admin": 2}


# ======================================================================= lifecycle
async def _housekeeping():
    while True:
        try:
            security.cleanup_sessions()
            dbmod.db.prune_events(int(get_settings()["log_keep_days"]))
        except Exception:  # noqa: BLE001
            log.exception("housekeeping")
        await asyncio.sleep(3600)


def _install_shutdown_hooks() -> None:
    """On SIGTERM/SIGINT, close the SSE streams first, then pass the signal to uvicorn.

    On shutdown uvicorn waits for open HTTP connections to close on their own, but the
    `StreamingResponse` for /api/stream does not receive `http.disconnect` until it finishes – so
    without this, shutdown hangs until `timeout_graceful_shutdown` (and CancelledError appears in the log).
    """
    import signal

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        prev = signal.getsignal(sig)
        if not callable(prev):
            continue

        def handler(signum, frame, _prev=prev):
            loop.call_soon_threadsafe(bus.sse_close_all)
            _prev(signum, frame)

        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init()
    notify.init()
    _install_shutdown_hooks()
    bus.emit("system", f"LockBridge {__version__} started" + (" (DEMO mode)" if config.DEMO else ""), source="system")
    await manager.start()
    engine.start()
    mqtt.client.start()
    alexa.emulator.start()
    ikea.client.restart()
    hk = asyncio.create_task(_housekeeping())
    yield
    bus.sse_close_all()
    hk.cancel()
    await manager.shutdown()


app = FastAPI(title="LockBridge", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

# No sensitive data – these may pass without an Access token (icons/manifest for PWA install, health check)
CF_PUBLIC_PATHS = ("/healthz", "/manifest.webmanifest", "/static/icons/")


@app.middleware("http")
async def cf_access_guard(request: Request, call_next):
    """When Cloudflare Access is enabled, every request must carry a valid Access JWT."""
    request.state.cf_email = None
    if not cfaccess.enabled() or request.url.path.startswith(CF_PUBLIC_PATHS):
        return await call_next(request)
    host = request.client.host if request.client else None
    if cfaccess.lan_bypass_ok(host, request.headers):
        return await call_next(request)
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    try:
        claims = await cfaccess.verifier.verify(token)
    except cfaccess.AccessDenied as e:
        log.warning("Cloudflare Access rejected %s %s: %s", host, request.url.path, e)
        return Response("403 – access allowed only through Cloudflare Access.", status_code=403,
                        media_type="text/plain; charset=utf-8")
    request.state.cf_email = claims.get("email") or claims.get("common_name")
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Standard security headers plus cache rules (defence in depth for the web surface)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; manifest-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    )
    if is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    path = request.url.path
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.endswith((".js", ".css", ".webmanifest")):
        response.headers.setdefault("Cache-Control", "no-cache")  # revalidate, so updates are not stale
    return response


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ======================================================================= auth helpers
def _from_local_proxy(request: Request) -> bool:
    """We trust X-Forwarded-* only when the request comes from a known proxy (the cloudflared machine, LB_PROXY_IPS)."""
    return config.TRUST_PROXY and bool(request.client) and request.client.host in config.PROXY_IPS


def client_ip(request: Request) -> str:
    if _from_local_proxy(request):
        if cf := request.headers.get("cf-connecting-ip"):
            return cf.strip()
        if fwd := request.headers.get("x-forwarded-for"):
            return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def who(request: Request) -> str:
    """IP + Cloudflare identity for the activity log entry."""
    email = getattr(request.state, "cf_email", None)
    return f"{client_ip(request)}, {email}" if email else client_ip(request)


def is_https(request: Request) -> bool:
    if _from_local_proxy(request) and request.headers.get("x-forwarded-proto") == "https":
        return True
    return request.url.scheme == "https"


def set_session_cookie(request: Request, resp: Response, token: str, stage: str):
    resp.set_cookie(
        security.SESSION_COOKIE, token, httponly=True, samesite="lax", secure=is_https(request),
        max_age=security.SESSION_DAYS * 86400 if stage == "full" else security.PENDING_SECONDS, path="/",
    )


class Principal:
    def __init__(self, name: str, role: str, user: dict | None = None, kind: str = "session"):
        self.name, self.role, self.user, self.kind = name, role, user, kind

    @property
    def id(self):
        return self.user["id"] if self.user else None


async def current(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        tok = security.check_api_token(auth[7:].strip())
        if not tok:
            raise HTTPException(401, "Invalid API token.")
        return Principal(f"API: {tok['name']}", tok["role"], kind="token")
    sess = security.get_session(request.cookies.get(security.SESSION_COOKIE))
    if not sess or sess["stage"] != "full":
        raise HTTPException(401, "Login required.")
    user = dbmod.db.one("SELECT * FROM users WHERE id=?", (sess["user_id"],))
    if not user:
        raise HTTPException(401, "Login required.")
    ok, why = security.user_access_ok(user)
    if not ok:
        raise HTTPException(403, why)
    # CSRF protection: state-changing requests from a browser must carry a custom header
    if request.method not in ("GET", "HEAD") and request.headers.get("x-lb") != "1":
        raise HTTPException(403, "CSRF check failed.")
    if user["must_change_pw"] and request.url.path not in ("/api/me/password", "/api/me", "/api/logout"):
        raise HTTPException(403, "You must change your password.")
    return Principal(user["display_name"], user["role"], user)


def need(role: str):
    async def dep(p: Principal = Depends(current)) -> Principal:
        if RANK.get(p.role, -1) < RANK[role]:
            raise HTTPException(403, "You do not have permission for this action.")
        return p

    return dep


def public_user(u: dict) -> dict:
    return {
        "id": u["id"], "username": u["username"], "display_name": u["display_name"], "role": u["role"],
        "totp_enabled": bool(u["totp_enabled"]), "must_change_pw": bool(u["must_change_pw"]),
        "active": bool(u["active"]), "valid_from": u["valid_from"], "valid_until": u["valid_until"],
        "created_at": u["created_at"], "last_login": u["last_login"], "notify": notify.user_prefs(u),
        "push_devices": dbmod.db.one("SELECT COUNT(*) n FROM push_subs WHERE user_id=?", (u["id"],))["n"],
    }


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Invalid JSON.") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "Expected a JSON object.")
    return data


def _pending_session(request: Request, stage: str) -> dict:
    sess = security.get_session(request.cookies.get(security.SESSION_COOKIE))
    if not sess or sess["stage"] != stage:
        raise HTTPException(401, "The session has expired, please log in again.")
    if request.headers.get("x-lb") != "1":
        raise HTTPException(403, "CSRF check failed.")
    return sess


def _upgrade_session(request: Request, resp: Response, sess: dict | None, user_id: int, stage: str):
    if sess:
        security.delete_session(request.cookies.get(security.SESSION_COOKIE))
    tok = security.create_session(user_id, stage, client_ip(request), request.headers.get("user-agent", ""))
    set_session_cookie(request, resp, tok, stage)


def _enroll_payload(user: dict) -> dict:
    uri = security.totp_uri(user["totp_secret"], user["username"], get_settings()["site_name"])
    return {"stage": "enroll", "secret": user["totp_secret"], "uri": uri, "qr": security.totp_qr_svg(uri)}


# ======================================================================= bootstrap / login
@app.get("/api/bootstrap")
async def bootstrap(request: Request):
    n = dbmod.db.one("SELECT COUNT(*) n FROM users")["n"]
    out = {"setup_needed": n == 0, "version": __version__, "demo": config.DEMO,
           "site_name": get_settings()["site_name"], "https": is_https(request),
           "public_url": config.PUBLIC_URL, "user": None, "stage": None}
    sess = security.get_session(request.cookies.get(security.SESSION_COOKIE))
    if sess:
        out["stage"] = sess["stage"]
        user = dbmod.db.one("SELECT * FROM users WHERE id=?", (sess["user_id"],))
        if user and sess["stage"] == "full":
            out["user"] = public_user(user)
            out["lock_configured"] = manager.is_configured()
        elif user and sess["stage"] == "enroll":
            out.update(_enroll_payload(user))
    return out


@app.post("/api/setup/admin")
async def setup_admin(request: Request):
    if dbmod.db.one("SELECT COUNT(*) n FROM users")["n"] > 0:
        raise HTTPException(409, "An administrator already exists.")
    if request.headers.get("x-lb") != "1":
        raise HTTPException(403, "CSRF check failed.")
    d = await body(request)
    username = (d.get("username") or "").strip()
    if len(username) < 3:
        raise HTTPException(400, "The username must be at least 3 characters long.")
    if prob := security.password_problem(d.get("password") or ""):
        raise HTTPException(400, prob)
    cur = dbmod.db.execute(
        "INSERT INTO users(username,display_name,pw_hash,role,totp_secret,created_at) VALUES(?,?,?,?,?,?)",
        (username, (d.get("display_name") or username).strip(), security.hash_password(d["password"]), "admin",
         security.new_totp_secret(), time.time()),
    )
    user = dbmod.db.one("SELECT * FROM users WHERE id=?", (cur.lastrowid,))
    bus.emit("user_changed", f"Administrator account '{username}' created.", source="system", user=username)
    resp = JSONResponse(_enroll_payload(user))
    _upgrade_session(request, resp, None, user["id"], "enroll")
    return resp


@app.post("/api/login")
async def login(request: Request):
    if request.headers.get("x-lb") != "1":
        raise HTTPException(403, "CSRF check failed.")
    d = await body(request)
    ip = client_ip(request)
    username = (d.get("username") or "").strip()
    keys = (f"ip:{ip}", f"user:{username.lower()}")
    if security.login_limiter.blocked(*keys):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    user = dbmod.db.one("SELECT * FROM users WHERE username=?", (username,))
    if not user or not security.verify_password(d.get("password") or "", user["pw_hash"]):
        security.login_limiter.fail(*keys)
        bus.emit("login_failed", f"Failed login for '{username}' ({who(request)}).", level="warning", source="web",
                 data={"ip": ip})
        raise HTTPException(401, "Incorrect username or password.")
    ok, why = security.user_access_ok(user)
    if not ok:
        raise HTTPException(403, why)
    if not user["totp_enabled"]:
        if not user["totp_secret"]:
            dbmod.db.execute("UPDATE users SET totp_secret=? WHERE id=?", (security.new_totp_secret(), user["id"]))
            user = dbmod.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
        resp = JSONResponse(_enroll_payload(user))
        _upgrade_session(request, resp, None, user["id"], "enroll")
        return resp
    resp = JSONResponse({"stage": "totp"})
    _upgrade_session(request, resp, None, user["id"], "totp")
    return resp


def _finish_login(request: Request, resp: Response, sess: dict, user: dict):
    ip = client_ip(request)
    security.login_limiter.reset(f"ip:{ip}", f"user:{user['username'].lower()}")
    dbmod.db.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), user["id"]))
    _upgrade_session(request, resp, sess, user["id"], "full")
    bus.emit("login", f"{user['display_name']} logged in ({who(request)}).", source="web", user=user["display_name"])


@app.post("/api/login/totp")
async def login_totp(request: Request):
    sess = _pending_session(request, "totp")
    d = await body(request)
    user = dbmod.db.one("SELECT * FROM users WHERE id=?", (sess["user_id"],))
    ip = client_ip(request)
    if security.login_limiter.blocked(f"ip:{ip}", f"user:{user['username'].lower()}"):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    if not security.verify_totp(user["id"], user["totp_secret"], d.get("code", "")):
        security.login_limiter.fail(f"ip:{ip}", f"user:{user['username'].lower()}")
        bus.emit("login_failed", f"Wrong 2FA code for '{user['username']}' ({ip}).", level="warning", source="web")
        raise HTTPException(401, "Wrong code. Check the time on your phone.")
    resp = JSONResponse({"stage": "full", "must_change_pw": bool(user["must_change_pw"])})
    _finish_login(request, resp, sess, user)
    return resp


@app.post("/api/login/enroll")
async def login_enroll(request: Request):
    sess = _pending_session(request, "enroll")
    d = await body(request)
    user = dbmod.db.one("SELECT * FROM users WHERE id=?", (sess["user_id"],))
    if not security.verify_totp(user["id"], user["totp_secret"], d.get("code", "")):
        raise HTTPException(401, "The code is not valid. Scan the QR code again and enter a new code.")
    dbmod.db.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user["id"],))
    resp = JSONResponse({"stage": "full", "must_change_pw": bool(user["must_change_pw"])})
    _finish_login(request, resp, sess, user)
    return resp


@app.post("/api/logout")
async def logout(request: Request):
    if tok := request.cookies.get(security.SESSION_COOKIE):
        security.delete_session(tok)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(security.SESSION_COOKIE, path="/")
    return resp


# ======================================================================= own account
@app.get("/api/me")
async def me(p: Principal = Depends(current)):
    if not p.user:
        return {"name": p.name, "role": p.role}
    return public_user(p.user)


@app.post("/api/me/password")
async def change_password(request: Request, p: Principal = Depends(current)):
    if not p.user:
        raise HTTPException(400, "Not available for an API token.")
    d = await body(request)
    if not security.verify_password(d.get("old") or "", p.user["pw_hash"]):
        raise HTTPException(400, "The current password is incorrect.")
    if prob := security.password_problem(d.get("new") or ""):
        raise HTTPException(400, prob)
    dbmod.db.execute("UPDATE users SET pw_hash=?, must_change_pw=0 WHERE id=?",
                     (security.hash_password(d["new"]), p.id))
    # sign out all other devices; this one gets a new session
    security.delete_user_sessions(p.id)
    resp = JSONResponse({"ok": True})
    _upgrade_session(request, resp, None, p.id, "full")
    bus.emit("user_changed", f"{p.name} changed the password.", source="web", user=p.name)
    return resp


@app.put("/api/me/notify")
async def set_notify(request: Request, p: Principal = Depends(current)):
    d = await body(request)
    prefs = {k: bool(d.get(k)) for k in list(notify.CATEGORIES) + ["own"] if k in d}
    dbmod.db.execute("UPDATE users SET notify=? WHERE id=?", (json.dumps(prefs), p.id))
    return {"ok": True}


@app.post("/api/me/logout-all")
async def logout_all(p: Principal = Depends(current)):
    security.delete_user_sessions(p.id)
    return {"ok": True}


# ======================================================================= lock
@app.get("/api/status")
async def status(p: Principal = Depends(current)):
    return manager.public_state()


async def _cmd(action: str, request: Request, p: Principal):
    try:
        await manager.command(action, p.name, "API" if p.kind == "token" else "web app")
    except LockError as e:
        raise HTTPException(409, str(e)) from None
    return manager.public_state()


@app.post("/api/lock")
async def do_lock(request: Request, p: Principal = Depends(current)):
    return await _cmd("lock", request, p)


@app.post("/api/unlock")
async def do_unlock(request: Request, p: Principal = Depends(current)):
    return await _cmd("unlock", request, p)


@app.post("/api/unlatch")
async def do_unlatch(request: Request, p: Principal = Depends(current)):
    return await _cmd("unlatch", request, p)


@app.post("/api/refresh")
async def do_refresh(p: Principal = Depends(current)):
    await manager.refresh()
    return manager.public_state()


@app.get("/api/stream")
async def stream(request: Request, p: Principal = Depends(current)):
    q = bus.sse_queue()
    see_events = RANK[p.role] >= RANK["user"]

    async def gen():
        idle = 0
        try:
            yield f"event: status\ndata: {json.dumps(manager.public_state())}\n\n"
            while True:
                # Short poll (1 s) so we break immediately when uvicorn closes the connection on
                # shutdown; otherwise a blocked q.get() holds shutdown until the timeout.
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), 1)
                    idle = 0
                except asyncio.TimeoutError:
                    idle += 1
                    if idle >= 20:  # ": ping" every ~20 s
                        idle = 0
                        yield ": ping\n\n"
                    continue
                if msg is None:  # bus.sse_close_all() – shutting down
                    break
                if msg["kind"] != "status" and not see_events:
                    continue
                yield f"event: {msg['kind']}\ndata: {json.dumps(msg['payload'], default=str)}\n\n"
        finally:
            bus.sse_close(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ======================================================================= logs
def _event_query(request: Request) -> tuple[str, list]:
    qp = request.query_params
    where, args = [], []
    if t := qp.get("type"):
        where.append("type IN (%s)" % ",".join("?" * len(t.split(","))))
        args += t.split(",")
    if lvl := qp.get("level"):
        where.append("level=?")
        args.append(lvl)
    if s := qp.get("q"):
        where.append("(message LIKE ? OR user LIKE ? OR source LIKE ?)")
        args += [f"%{s}%"] * 3
    if b := qp.get("before"):
        where.append("id < ?")
        args.append(int(b))
    if since := qp.get("since"):
        where.append("ts >= ?")
        args.append(float(since))
    return (" WHERE " + " AND ".join(where)) if where else "", args


@app.get("/api/events")
async def events(request: Request, p: Principal = Depends(need("user"))):
    w, args = _event_query(request)
    limit = min(int(request.query_params.get("limit", 100)), 500)
    rows = dbmod.db.all(f"SELECT * FROM events{w} ORDER BY id DESC LIMIT ?", args + [limit])
    for r in rows:
        r["data"] = json.loads(r["data"] or "{}")
    return rows


@app.get("/api/events.csv")
async def events_csv(request: Request, p: Principal = Depends(need("admin"))):
    w, args = _event_query(request)
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=";")
    wr.writerow(["time", "level", "type", "user", "source", "message"])
    for r in dbmod.db.all(f"SELECT * FROM events{w} ORDER BY id DESC LIMIT 100000", args):
        wr.writerow([datetime.fromtimestamp(r["ts"]).isoformat(sep=" ", timespec="seconds"), r["level"], r["type"],
                     r["user"] or "", r["source"] or "", r["message"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=lockbridge-log.csv"})


@app.get("/api/stats")
async def stats(p: Principal = Depends(need("user"))):
    since = time.time() - 7 * 86400
    rows = dbmod.db.all("SELECT type, COUNT(*) n FROM events WHERE ts>=? GROUP BY type", (since,))
    by_day = dbmod.db.all(
        "SELECT date(ts,'unixepoch','localtime') d, COUNT(*) n FROM events WHERE ts>=? AND type IN ('unlocked','unlatched') GROUP BY d ORDER BY d",
        (since,))
    return {"by_type": {r["type"]: r["n"] for r in rows}, "unlocks_by_day": by_day}


# ======================================================================= users
@app.get("/api/users")
async def users(p: Principal = Depends(need("admin"))):
    return [public_user(u) for u in dbmod.db.all("SELECT * FROM users ORDER BY role, display_name")]


def _user_fields(d: dict, existing: dict | None) -> dict:
    out = {}
    if "display_name" in d:
        out["display_name"] = (d["display_name"] or "").strip() or (existing or {}).get("username")
    if "role" in d:
        if d["role"] not in security.ROLES:
            raise HTTPException(400, "Unknown role.")
        out["role"] = d["role"]
    for k in ("valid_from", "valid_until"):
        if k in d:
            v = d[k] or None
            if v:
                try:
                    datetime.fromisoformat(v)
                except ValueError:
                    raise HTTPException(400, f"Invalid date: {v}") from None
            out[k] = v
    if "active" in d:
        out["active"] = 1 if d["active"] else 0
    return out


def _admins_left(excluding: int) -> int:
    return dbmod.db.one("SELECT COUNT(*) n FROM users WHERE role='admin' AND active=1 AND id!=?", (excluding,))["n"]


@app.post("/api/users")
async def create_user(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    username = (d.get("username") or "").strip()
    if len(username) < 3 or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Username: at least 3 characters, letters, digits, . _ -")
    if dbmod.db.one("SELECT id FROM users WHERE username=?", (username,)):
        raise HTTPException(409, "The username is already taken.")
    if prob := security.password_problem(d.get("password") or ""):
        raise HTTPException(400, prob)
    f = _user_fields({"display_name": d.get("display_name") or username, "role": d.get("role", "user"), **d}, None)
    cur = dbmod.db.execute(
        "INSERT INTO users(username,display_name,pw_hash,role,totp_secret,must_change_pw,valid_from,valid_until,created_at)"
        " VALUES(?,?,?,?,?,1,?,?,?)",
        (username, f["display_name"], security.hash_password(d["password"]), f["role"], security.new_totp_secret(),
         f.get("valid_from"), f.get("valid_until"), time.time()),
    )
    bus.emit("user_changed", f"{p.name} added user '{f['display_name']}' ({f['role']}).", source="web", user=p.name)
    return public_user(dbmod.db.one("SELECT * FROM users WHERE id=?", (cur.lastrowid,)))


@app.put("/api/users/{uid}")
async def update_user(uid: int, request: Request, p: Principal = Depends(need("admin"))):
    u = dbmod.db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404, "The user does not exist.")
    d = await body(request)
    f = _user_fields(d, u)
    if u["role"] == "admin" and (f.get("role", "admin") != "admin" or f.get("active") == 0) and _admins_left(uid) == 0:
        raise HTTPException(400, "At least one active administrator must remain.")
    if d.get("password"):
        if prob := security.password_problem(d["password"]):
            raise HTTPException(400, prob)
        f["pw_hash"] = security.hash_password(d["password"])
        f["must_change_pw"] = 1
    if d.get("reset_2fa"):
        f["totp_secret"] = security.new_totp_secret()
        f["totp_enabled"] = 0
    if f:
        dbmod.db.execute(f"UPDATE users SET {', '.join(k + '=?' for k in f)} WHERE id=?", list(f.values()) + [uid])
    if "pw_hash" in f or "totp_secret" in f or f.get("active") == 0:
        security.delete_user_sessions(uid)
    bus.emit("user_changed", f"{p.name} modified user '{u['display_name']}'.", source="web", user=p.name)
    return public_user(dbmod.db.one("SELECT * FROM users WHERE id=?", (uid,)))


@app.delete("/api/users/{uid}")
async def delete_user(uid: int, p: Principal = Depends(need("admin"))):
    u = dbmod.db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not u:
        raise HTTPException(404, "The user does not exist.")
    if uid == p.id:
        raise HTTPException(400, "You cannot delete your own account.")
    if u["role"] == "admin" and _admins_left(uid) == 0:
        raise HTTPException(400, "At least one administrator must remain.")
    security.delete_user_sessions(uid)
    dbmod.db.execute("DELETE FROM push_subs WHERE user_id=?", (uid,))
    dbmod.db.execute("DELETE FROM users WHERE id=?", (uid,))
    bus.emit("user_changed", f"{p.name} deleted user '{u['display_name']}'.", source="web", user=p.name)
    return {"ok": True}


# ======================================================================= API tokens
@app.get("/api/tokens")
async def tokens(p: Principal = Depends(need("admin"))):
    return dbmod.db.all("SELECT id,name,role,created_at,last_used FROM api_tokens ORDER BY id")


@app.post("/api/tokens")
async def create_token(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    role = d.get("role", "user")
    if role not in ("user", "guest", "admin"):
        raise HTTPException(400, "Unknown role.")
    name = (d.get("name") or "").strip() or "token"
    tok = security.create_api_token(name, role)
    bus.emit("user_changed", f"{p.name} created API token '{name}'.", source="web", user=p.name)
    return {"token": tok}


@app.delete("/api/tokens/{tid}")
async def delete_token(tid: int, p: Principal = Depends(need("admin"))):
    dbmod.db.execute("DELETE FROM api_tokens WHERE id=?", (tid,))
    return {"ok": True}


# ======================================================================= lock setup
_cloud: dict[int, CloudLogin] = {}
# Keys obtained from an import (Home Assistant / cloud) stay on the server: the UI
# only receives a masked hint plus an index, so the key never reaches the browser.
_import_cache: dict[int, list[dict]] = {}


def _mask_key(key: str | None) -> str:
    key = (key or "").strip()
    return ("*" * max(0, len(key) - 4)) + key[-4:] if key else ""


def _cache_keys(pid: int, items: list[dict]) -> list[dict]:
    _import_cache[pid] = [dict(item) for item in items]
    return [
        {k: v for k, v in item.items() if k != "key"}
        | {"index": idx, "key_hint": _mask_key(item.get("key"))}
        for idx, item in enumerate(items)
    ]


@app.get("/api/lockcfg")
async def get_lockcfg(p: Principal = Depends(need("admin"))):
    c = manager.get_cfg()
    adapters = sorted(os.listdir("/sys/class/bluetooth")) if os.path.isdir("/sys/class/bluetooth") else []
    return {
        "address": c.get("address", ""), "local_name": c.get("local_name", ""), "slot": c.get("slot"),
        "has_key": bool(secret.load_key()), "adapter": c.get("adapter", ""), "always_connected": bool(c.get("always_connected")),
        "unlatch": bool(c.get("unlatch")), "adapters": [a for a in adapters if a.startswith("hci")],
        "demo": config.DEMO,
    }


@app.put("/api/lockcfg")
async def put_lockcfg(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    c = manager.get_cfg()
    address = (d.get("address") or c.get("address") or "").strip().upper()
    if len(address) != 17 or address.count(":") != 5:
        raise HTTPException(400, "The Bluetooth address must be in the form AA:BB:CC:DD:EE:FF.")
    key = d.get("key") or c.get("key")
    if not d.get("key") and d.get("import_index") is not None:
        try:
            key = _import_cache.pop(p.id, [])[int(d["import_index"])]["key"]
        except (IndexError, KeyError, TypeError, ValueError):
            raise HTTPException(400, "The imported key has expired – import it again.") from None
    try:
        key, slot = validate_key(key or "", d.get("slot", c.get("slot")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    secret.save_key(key)
    c.update(address=address, slot=slot, local_name=(d.get("local_name") or c.get("local_name") or "").strip(),
             adapter=(d.get("adapter") or "").strip(), always_connected=bool(d.get("always_connected")),
             unlatch=bool(d.get("unlatch")))
    c.pop("key", None)  # the key never goes into the database/backup
    dbmod.db.set("lock", c)
    bus.emit("system", f"{p.name} saved the lock settings ({address}).", source="web", user=p.name)
    await manager.restart()
    return {"ok": True}


@app.delete("/api/lockcfg")
async def del_lockcfg(p: Principal = Depends(need("admin"))):
    secret.clear_key()
    dbmod.db.set("lock", {})
    await manager.restart()
    bus.emit("system", f"{p.name} removed the lock settings.", source="web", user=p.name)
    return {"ok": True}


@app.post("/api/lockcfg/scan")
async def scan(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    return await manager.scan(min(30, max(3, float(d.get("seconds", 10)))))


@app.post("/api/lockcfg/import_ha")
async def import_ha(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    try:
        return _cache_keys(p.id, parse_ha_config_entries(d.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/lockcfg/cloud/login")
async def cloud_login(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    if old := _cloud.pop(p.id, None):
        await old.close()
    try:
        cl = CloudLogin(d.get("brand", "yale_access"), d.get("email", ""), d.get("password", ""))
        _cloud[p.id] = cl
        state = await cl.login()
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Cloud login failed: {e}") from None
    return {"state": state}


@app.post("/api/lockcfg/cloud/verify")
async def cloud_verify(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    cl = _cloud.get(p.id)
    if not cl:
        raise HTTPException(400, "Log in first.")
    try:
        await cl.verify(d.get("code", ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"state": "ok"}


@app.get("/api/lockcfg/cloud/locks")
async def cloud_locks(p: Principal = Depends(need("admin"))):
    cl = _cloud.pop(p.id, None)
    if not cl:
        raise HTTPException(400, "Log in first.")
    try:
        return _cache_keys(p.id, await cl.locks())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Fetching locks failed: {e}") from None
    finally:
        await cl.close()


# ======================================================================= automations
@app.get("/api/automations")
async def automations(p: Principal = Depends(need("admin"))):
    return {"items": load_all(), "templates": TEMPLATES, "event_triggers": EVENT_TRIGGERS}


def _automation_fields(d: dict) -> tuple:
    name = (d.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "An automation must have a name.")
    trig = d.get("trigger") or {}
    if trig.get("type") not in ("event", "state_for", "time", "webhook", "ikea", "mqtt"):
        raise HTTPException(400, "Unknown trigger.")
    if trig["type"] == "webhook" and not trig.get("hook"):
        trig["hook"] = security.random_secret()
    acts = d.get("actions") or []
    if not acts:
        raise HTTPException(400, "Add at least one action.")
    return name, 1 if d.get("enabled", True) else 0, json.dumps(trig), json.dumps(d.get("conditions") or []), json.dumps(acts)


@app.post("/api/automations")
async def create_automation(request: Request, p: Principal = Depends(need("admin"))):
    f = _automation_fields(await body(request))
    dbmod.db.execute("INSERT INTO automations(name,enabled,trigger,conditions,actions) VALUES(?,?,?,?,?)", f)
    engine.reevaluate_timers()
    if json.loads(f[2]).get("type") == "mqtt":
        mqtt.client.restart()  # new topic subscriptions
    return {"ok": True}


@app.put("/api/automations/{aid}")
async def update_automation(aid: int, request: Request, p: Principal = Depends(need("admin"))):
    f = _automation_fields(await body(request))
    dbmod.db.execute("UPDATE automations SET name=?,enabled=?,trigger=?,conditions=?,actions=? WHERE id=?", f + (aid,))
    engine.reevaluate_timers()
    if json.loads(f[2]).get("type") == "mqtt":
        mqtt.client.restart()  # new topic subscriptions
    return {"ok": True}


@app.delete("/api/automations/{aid}")
async def delete_automation(aid: int, p: Principal = Depends(need("admin"))):
    dbmod.db.execute("DELETE FROM automations WHERE id=?", (aid,))
    engine.reevaluate_timers()
    return {"ok": True}


@app.post("/api/automations/{aid}/run")
async def run_automation(aid: int, p: Principal = Depends(need("admin"))):
    a = next((x for x in load_all() if x["id"] == aid), None)
    if not a:
        raise HTTPException(404, "Does not exist.")
    asyncio.create_task(engine.run(a, {}, manual_by=p.name))
    return {"ok": True}


hook_limiter = security.RateLimiter(max_failures=20, window=600)


@app.api_route("/api/hook/{hook}", methods=["GET", "POST"])
async def webhook(hook: str, request: Request):
    ip = client_ip(request)
    if hook_limiter.blocked(ip):
        raise HTTPException(429, "Too many requests.")
    payload = {}
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
    n = engine.fire_webhook(hook, payload if isinstance(payload, dict) else {})
    if not n:
        hook_limiter.fail(ip)
        raise HTTPException(404, "Unknown webhook.")
    return {"ok": True, "triggered": n}


# ======================================================================= integrations
SECRET_FIELDS = {"mqtt": ["password"], "ikea": ["token"], "ntfy": ["token"], "telegram": ["bot_token"]}


@app.get("/api/integrations")
async def integrations(p: Principal = Depends(need("admin"))):
    integ = dbmod.db.get("integrations", {}) or {}
    out = {
        "mqtt": {**mqtt.get_cfg()},
        "alexa": {**alexa.get_cfg()},
        "ikea": {**ikea.get_cfg()},
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": "", "token": "",
                 "categories": list(notify.CATEGORIES), **integ.get("ntfy", {})},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": "", "categories": list(notify.CATEGORIES),
                     **integ.get("telegram", {})},
    }
    for name, fields in SECRET_FIELDS.items():
        for f in fields:
            out[name][f"has_{f}"] = bool(out[name].get(f))
            out[name][f] = ""
    out["status"] = {"mqtt": mqtt.client.status, "alexa": alexa.emulator.status, "ikea": ikea.client.status}
    out["host"] = {"hostname": socket.gethostname(), "ip": alexa.local_ip()}
    out["categories"] = notify.CATEGORIES
    return out


@app.put("/api/integrations/{name}")
async def put_integration(name: str, request: Request, p: Principal = Depends(need("admin"))):
    if name not in ("mqtt", "alexa", "ikea", "ntfy", "telegram"):
        raise HTTPException(404, "Unknown integration.")
    d = await body(request)
    integ = dbmod.db.get("integrations", {}) or {}
    cur = integ.get(name, {})
    for f in SECRET_FIELDS.get(name, []):
        if not d.get(f) and not d.pop(f"clear_{f}", False):
            d.pop(f, None)  # an empty field = keep the existing secret
    for k in list(d):
        if k.startswith("has_"):
            d.pop(k)
    cur.update(d)
    integ[name] = cur
    dbmod.db.set("integrations", integ)
    if name == "mqtt":
        mqtt.client.restart()
    elif name == "alexa":
        await alexa.emulator.restart()
    elif name == "ikea":
        ikea.client.restart()
    bus.emit("system", f"{p.name} modified integration '{name}'.", source="web", user=p.name)
    return {"ok": True}


@app.post("/api/integrations/test/{name}")
async def test_integration(name: str, p: Principal = Depends(need("admin"))):
    if name in ("ntfy", "telegram"):
        await notify._external("automation", "LockBridge test", f"Test notification ({p.name}).")
        return {"ok": True}
    raise HTTPException(400, "Test not available.")


@app.post("/api/ikea/pair/start")
async def ikea_pair_start(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    try:
        await ikea.client.pair_start((d.get("host") or "").strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Hub is unavailable: {e}") from None
    return {"ok": True}


@app.post("/api/ikea/pair/finish")
async def ikea_pair_finish(p: Principal = Depends(need("admin"))):
    try:
        return {"done": await ikea.client.pair_finish()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from None


@app.get("/api/ikea/devices")
async def ikea_devices(p: Principal = Depends(need("admin"))):
    try:
        return {"devices": await ikea.client.devices(), "scenes": await ikea.client.scenes(),
                "recent": list(ikea.client.recent)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from None


# ======================================================================= push notifications
@app.get("/api/push/key")
async def push_key(p: Principal = Depends(current)):
    return {"key": notify.public_key()}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request, p: Principal = Depends(current)):
    if not p.user:
        raise HTTPException(400, "For users only.")
    sub = await body(request)
    if not sub.get("endpoint") or not sub.get("keys"):
        raise HTTPException(400, "Invalid subscription.")
    dbmod.db.execute(
        "INSERT INTO push_subs(user_id,endpoint,sub,ua,created_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, sub=excluded.sub",
        (p.id, sub["endpoint"], json.dumps(sub), request.headers.get("user-agent", "")[:200], time.time()),
    )
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request, p: Principal = Depends(current)):
    d = await body(request)
    dbmod.db.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (d.get("endpoint"), p.id))
    return {"ok": True}


@app.post("/api/push/test")
async def push_test(p: Principal = Depends(current)):
    n = await notify.push_to_user(p.id, {"title": "🔔 LockBridge", "body": "Notifications work!", "url": "/#/", "tag": "test"})
    if not n:
        raise HTTPException(400, "No device is subscribed or sending failed.")
    return {"sent": n}


@app.get("/api/install/qr")
async def install_qr(p: Principal = Depends(current)):
    """QR code of the public (HTTPS) address – for opening and installing the app on a phone."""
    if not config.PUBLIC_URL:
        raise HTTPException(400, "The public address is not set (LB_PUBLIC_URL).")
    svg = security.qr_svg(config.PUBLIC_URL, scale=8)
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=300"})


# ======================================================================= settings and system
@app.get("/api/settings")
async def settings(p: Principal = Depends(need("admin"))):
    return get_settings()


@app.put("/api/settings")
async def put_settings(request: Request, p: Principal = Depends(need("admin"))):
    d = await body(request)
    s = get_settings()
    for k, default in default_settings().items():
        if k in d:
            s[k] = type(default)(d[k]) if not isinstance(default, bool) else bool(d[k])
    if not 0 < s["battery_critical"] < s["battery_warn"] < 100:
        raise HTTPException(400, "Battery thresholds: 0 < critical < warning < 100.")
    dbmod.db.set("settings", s)
    manager._changed()
    return s


def _cpu_temp() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


@app.get("/api/system")
async def system(request: Request, p: Principal = Depends(need("admin"))):
    du = shutil.disk_usage(config.DATA_DIR)
    model = ""
    try:
        model = Path("/proc/device-tree/model").read_text().strip("\x00")
    except OSError:
        model = platform.machine()
    return {
        "version": __version__, "hostname": socket.gethostname(), "model": model, "python": platform.python_version(),
        "uptime": time.time() - STARTED, "cpu_temp": _cpu_temp(), "demo": config.DEMO,
        "disk_free_gb": round(du.free / 1e9, 1), "db_size_mb": round(os.path.getsize(dbmod.db.path) / 1e6, 2),
        "events": dbmod.db.one("SELECT COUNT(*) n FROM events")["n"], "scanner": manager.state.get("scanner"),
        "cf_access": {
            "enabled": cfaccess.enabled(), "team": cfaccess.issuer() if cfaccess.enabled() else None,
            "emails": sorted(config.CF_EMAILS), "lan_bypass": config.CF_LAN_BYPASS,
            "proxy_ips": sorted(config.PROXY_IPS - {"127.0.0.1", "::1"}),
            "you": getattr(request.state, "cf_email", None),
        },
        "https": is_https(request),
    }


@app.post("/api/system/restart-lock")
async def restart_lock(p: Principal = Depends(need("admin"))):
    await manager.restart()
    return {"ok": True}


@app.get("/api/system/backup")
async def backup(p: Principal = Depends(need("admin"))):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    dbmod.db.backup_to(path)
    data = Path(path).read_bytes()
    os.unlink(path)
    bus.emit("system", f"{p.name} downloaded a backup.", source="web", user=p.name)
    name = f"lockbridge-backup-{datetime.now():%Y%m%d-%H%M}.db"
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


# ======================================================================= static files (PWA)
@app.get("/")
async def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def sw():
    return FileResponse(config.STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
async def manifest():
    m = json.loads((config.STATIC_DIR / "manifest.webmanifest").read_text())
    m["name"] = f"LockBridge – {get_settings()['site_name']}"
    return JSONResponse(m, media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
