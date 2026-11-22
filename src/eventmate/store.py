"""SQLite storage for EventMate. One small file holds every event."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'general',
    starts_at TEXT NOT NULL,
    venue TEXT NOT NULL DEFAULT '',
    capacity INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attendees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'guest',
    checked_in_at TEXT,
    UNIQUE(event_id, name)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    host TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    due TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    paid_by TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    env = os.environ.get("EVENTMATE_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".eventmate" / "eventmate.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create if needed) the database. Use ':memory:' for tests."""
    path = str(path or default_db_path())
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="minutes")


def parse_dt(value: str) -> datetime:
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' / ISO 8601."""
    try:
        return datetime.fromisoformat(value.strip().replace(" ", "T", 1))
    except ValueError as exc:
        raise ValueError(f"Unrecognised date/time {value!r}; use 'YYYY-MM-DD HH:MM'.") from exc
