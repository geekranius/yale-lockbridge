"""SQLite storage: users, sessions, events, automations, settings."""

import json
import sqlite3
import threading
import time
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    display_name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    must_change_pw INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    valid_from TEXT,
    valid_until TEXT,
    notify TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    last_login REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ip TEXT,
    ua TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT,
    user TEXT,
    message TEXT NOT NULL,
    data TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS push_subs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    endpoint TEXT UNIQUE NOT NULL,
    sub TEXT NOT NULL,
    ua TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS automations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    trigger TEXT NOT NULL,
    conditions TEXT NOT NULL DEFAULT '[]',
    actions TEXT NOT NULL DEFAULT '[]',
    last_run REAL
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at REAL NOT NULL,
    last_used REAL
);
"""


class DB:
    def __init__(self, path=None):
        self.path = path or (config.DATA_DIR / "lockbridge.db")
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    # --- key/value settings ---
    def get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        if row is None:
            return default
        return json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def prune_events(self, keep_days: int) -> None:
        self.execute("DELETE FROM events WHERE ts < ?", (time.time() - keep_days * 86400,))

    def backup_to(self, dest_path: str) -> None:
        with self._lock:
            dest = sqlite3.connect(dest_path)
            self.conn.backup(dest)
            dest.close()


db: DB | None = None


def init() -> DB:
    global db
    config.ensure_dirs()
    db = DB()
    return db
