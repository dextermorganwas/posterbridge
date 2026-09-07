# app/cache.py
#
# Small sqlite-backed cache (selection results + a generic app_state table)
# plus an in-memory async request-coalescing helper so that N simultaneous
# requests for the same artwork/sash trigger exactly one upstream fetch.
#
# claim_app_state_slot()/set_app_state() exist to satisfy the interface
# app/sash/imdb_dataset.py (adapted from PostersPlus) expects. PostersPlus
# uses this to coordinate a refresh claim across multiple uvicorn *workers*;
# PosterBridge is designed to run as a single worker process (see
# entrypoint.sh), so the "claim" here only needs to guard against the
# refresh loop firing twice in the same process, which a plain timestamp
# check covers.
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable

from app.config import DB_PATH

logger = logging.getLogger(__name__)

_local = threading.local()
_app_state_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS selection_cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS digital_release_cache ("
            "imdb_id TEXT PRIMARY KEY, posted_at INTEGER NOT NULL)"
        )
        conn.commit()
        _local.conn = conn
    return conn


# ---------------------------------------------------------------------------
# Generic app_state table
# ---------------------------------------------------------------------------

def get_app_state(key: str) -> str | None:
    row = _get_db().execute(
        "SELECT value FROM app_state WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def set_app_state(key: str, value: str) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def claim_app_state_slot(key: str, now: float, min_interval: float) -> bool:
    """True if the caller may proceed with the guarded action (and the claim
    timestamp has been recorded), False if another recent claim is still
    within *min_interval* seconds.
    """
    with _app_state_lock:
        raw = get_app_state(key)
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        if now - last < min_interval:
            return False
        set_app_state(key, str(now))
        return True


# ---------------------------------------------------------------------------
# Selection cache — "which URL/source won the fallback chain for this key"
# ---------------------------------------------------------------------------

def get_selection(key: str) -> Any | None:
    row = _get_db().execute(
        "SELECT value, expires_at FROM selection_cache WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    value, expires_at = row
    if expires_at < time.time():
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def set_selection(key: str, value: Any, ttl_seconds: float) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO selection_cache (key, value, expires_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
        (key, json.dumps(value), time.time() + ttl_seconds),
    )
    conn.commit()


def prune_expired(now: float | None = None) -> int:
    now = now if now is not None else time.time()
    conn = _get_db()
    cur = conn.execute("DELETE FROM selection_cache WHERE expires_at < ?", (now,))
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Digital-release cache (r/movieleaks early-signal, app/sash/digital_release.py)
# ---------------------------------------------------------------------------

def is_digital_release(imdb_id: str) -> bool:
    row = _get_db().execute(
        "SELECT 1 FROM digital_release_cache WHERE imdb_id = ?", (imdb_id,)
    ).fetchone()
    return row is not None


def add_digital_releases(entries: list[tuple[str, int]]) -> int:
    if not entries:
        return 0
    conn = _get_db()
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO digital_release_cache (imdb_id, posted_at) VALUES (?, ?)",
        entries,
    )
    conn.commit()
    return conn.total_changes - before


def prune_digital_releases(max_age_days: int) -> int:
    cutoff = time.time() - max_age_days * 86400
    conn = _get_db()
    cur = conn.execute("DELETE FROM digital_release_cache WHERE posted_at < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Request coalescing — many simultaneous requests for the same key await one
# in-flight computation instead of each triggering their own upstream calls.
# ---------------------------------------------------------------------------

class _Coalescer:
    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future] = {}
        self._guard = asyncio.Lock()

    async def run(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        async with self._guard:
            fut = self._inflight.get(key)
            if fut is None:
                fut = asyncio.ensure_future(self._invoke(key, factory))
                self._inflight[key] = fut
        return await fut

    async def _invoke(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await factory()
        finally:
            async with self._guard:
                self._inflight.pop(key, None)


coalescer = _Coalescer()


async def coalesced(key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run *factory* at most once for concurrent callers sharing *key*."""
    return await coalescer.run(key, factory)


def close_all() -> None:
    """Best-effort close of the thread-local sqlite connection on shutdown."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
