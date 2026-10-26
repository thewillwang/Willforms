"""SQLite-backed `Memory` using the stdlib `sqlite3` module.

One connection, shared across threads and serialised by a lock. Every blocking
call runs in a worker thread via `asyncio.to_thread`, so the event loop never
waits on disk.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from typing import Any, Callable, TypeVar

from embody.cloud.ports import Memory

_T = TypeVar("_T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    device     TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (device, key)
);
CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device     TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,  -- JSON
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_by_device ON turns (device, id);
"""


def _jsonable(obj: Any) -> Any:
    """Turn SDK / pydantic objects into plain JSON-compatible values.

    `exclude_none` keeps the stored blocks identical to what the API accepted
    on the way in, so they can be sent back as history without null fields.
    """
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return _jsonable(dump(mode="json", exclude_none=True))
    return obj


def _is_plain_user(msg: dict[str, Any]) -> bool:
    """A user turn that does not carry tool results (string, or blocks without tool_result)."""
    if msg["role"] != "user":
        return False
    content = msg["content"]
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _drop_leading_until_plain_user(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The API needs history to open with a plain user turn. A window cut in the
    middle of a tool exchange opens with an orphan `tool_result` (or an assistant
    turn); drop entries until a plain user turn appears."""
    i = 0
    while i < len(turns) and not _is_plain_user(turns[i]):
        i += 1
    return turns[i:]


class SqliteMemory(Memory):
    """Per-device facts (key/value) and conversation turns in one SQLite file.

    `path` may be ":memory:" for an ephemeral database (tests, dry runs).
    """

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    async def _run(self, fn: Callable[..., _T], *args: Any) -> _T:
        def locked() -> _T:
            with self._lock:
                return fn(*args)

        return await asyncio.to_thread(locked)

    # ── facts ──

    async def remember(self, device: str, key: str, value: str) -> None:
        await self._run(self._remember, device, key, value)

    def _remember(self, device: str, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO facts (device, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (device, key) DO UPDATE SET "
                "value = excluded.value, updated_at = excluded.updated_at",
                (device, key, value, time.time()),
            )

    async def recall(self, device: str, key: str | None = None) -> dict[str, str]:
        return await self._run(self._recall, device, key)

    def _recall(self, device: str, key: str | None) -> dict[str, str]:
        if key is None:
            rows = self._conn.execute(
                "SELECT key, value FROM facts WHERE device = ?", (device,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT key, value FROM facts WHERE device = ? AND key = ?", (device, key)
            ).fetchall()
        return dict(rows)

    # ── turns ──

    async def append_turn(self, device: str, role: str, content: Any) -> None:
        payload = json.dumps(_jsonable(content), ensure_ascii=False, default=str)
        await self._run(self._append_turn, device, role, payload)

    def _append_turn(self, device: str, role: str, payload: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO turns (device, role, content, created_at) VALUES (?, ?, ?, ?)",
                (device, role, payload, time.time()),
            )

    async def history(self, device: str, limit: int) -> list[dict[str, Any]]:
        return await self._run(self._history, device, limit)

    def _history(self, device: str, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        rows = self._conn.execute(
            "SELECT role, content FROM turns WHERE device = ? ORDER BY id DESC LIMIT ?",
            (device, limit),
        ).fetchall()
        turns = [{"role": role, "content": json.loads(content)} for role, content in reversed(rows)]
        return _drop_leading_until_plain_user(turns)

    # ── lifecycle ──

    async def close(self) -> None:
        await self._run(self._conn.close)
