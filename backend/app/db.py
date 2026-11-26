"""Global SQLite store for per-book mutable settings.

One database holds every book. A book directory (``books.dir``, canonical path)
is the stable key; body text, chapter index, ledgers, prompts and templates stay
on disk.

Concurrency: SQLite is opened in WAL mode with a 5s busy timeout, and every write
helper also takes a process-wide lock so sibling threads never interleave
transactions inside this service.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .core.home import studio_home

_WRITE_LOCK = threading.RLock()
_SCHEMA_LOCK = threading.Lock()
_ready: set[str] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def db_path() -> Path:
    """``DSH_NOVEL_DB`` when set, else ``<数据目录>/studio.db``（默认 ``<仓库>/data``）。"""
    raw = (os.environ.get("DSH_NOVEL_DB") or "").strip()
    path = Path(raw).expanduser() if raw else studio_home() / "studio.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    dir TEXT UNIQUE NOT NULL,
    title TEXT,
    data_json TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bible (
    book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    data_json TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS volumes (
    book_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    title TEXT,
    from_chapter INTEGER,
    to_chapter INTEGER,
    data_json TEXT,
    PRIMARY KEY (book_id, idx)
);

CREATE TABLE IF NOT EXISTS foreshadows (
    book_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT,
    kind TEXT,
    plant_chapter INTEGER,
    due_chapter INTEGER,
    status TEXT,
    data_json TEXT,
    PRIMARY KEY (book_id, id)
);

CREATE TABLE IF NOT EXISTS outlines (
    book_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    title TEXT,
    data_json TEXT,
    detail TEXT,
    updated_at TEXT,
    PRIMARY KEY (book_id, chapter)
);

CREATE TABLE IF NOT EXISTS segments (
    book_id TEXT NOT NULL,
    id TEXT NOT NULL,
    from_chapter INTEGER,
    to_chapter INTEGER,
    data_json TEXT,
    PRIMARY KEY (book_id, id)
);

CREATE TABLE IF NOT EXISTS chapter_memory (
    book_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    summary TEXT,
    data_json TEXT,
    source TEXT,
    created_at TEXT,
    PRIMARY KEY (book_id, chapter)
);

CREATE TABLE IF NOT EXISTS volume_memory (
    book_id TEXT NOT NULL,
    volume_index INTEGER NOT NULL,
    title TEXT,
    from_chapter INTEGER,
    to_chapter INTEGER,
    summary TEXT,
    data_json TEXT,
    created_at TEXT,
    PRIMARY KEY (book_id, volume_index)
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT NOT NULL,
    chapter INTEGER,
    story_time TEXT,
    place TEXT,
    event TEXT,
    kind TEXT,
    reveal_chapter INTEGER,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS character_states (
    book_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    name TEXT NOT NULL,
    data_json TEXT,
    PRIMARY KEY (book_id, chapter, name)
);

CREATE TABLE IF NOT EXISTS relations (
    book_id TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    state TEXT,
    data_json TEXT,
    PRIMARY KEY (book_id, chapter, a, b)
);

CREATE TABLE IF NOT EXISTS writing_runs (
    id TEXT PRIMARY KEY,
    book_id TEXT,
    run_id TEXT,
    from_chapter INTEGER,
    to_chapter INTEGER,
    status TEXT,
    data_json TEXT,
    started_at TEXT,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS ledger (
    book_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (book_id, kind, seq)
);

CREATE INDEX IF NOT EXISTS idx_ledger_book_kind ON ledger(book_id, kind, seq);
CREATE INDEX IF NOT EXISTS idx_foreshadows_book_status ON foreshadows(book_id, status);
CREATE INDEX IF NOT EXISTS idx_timeline_book_chapter ON timeline_events(book_id, chapter);
CREATE INDEX IF NOT EXISTS idx_writing_runs_book ON writing_runs(book_id, run_id);
"""


def _ensure_schema(conn: sqlite3.Connection, path: Path) -> None:
    key = str(path)
    if key in _ready:
        return
    with _SCHEMA_LOCK:
        if key in _ready:
            return
        conn.executescript(SCHEMA)
        conn.commit()
        _ready.add(key)


def connect() -> sqlite3.Connection:
    path = db_path()
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn, path)
    return conn


def init_db() -> None:
    """Create every table if missing. Idempotent."""
    conn = connect()
    conn.close()


@contextmanager
def write_tx() -> Iterator[sqlite3.Connection]:
    """Serialized write transaction: process lock + connection-scoped commit."""
    with _WRITE_LOCK:
        conn = connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()


@contextmanager
def read_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


_BOOK_TABLES = (
    "bible",
    "volumes",
    "foreshadows",
    "outlines",
    "segments",
    "chapter_memory",
    "volume_memory",
    "timeline_events",
    "character_states",
    "relations",
    "writing_runs",
    "ledger",
)


def delete_book_data(root: str | os.PathLike) -> bool:
    """Drop every DB row belonging to a book directory.

    Called after the book directory is removed so a later book created at the
    same path starts clean instead of resurrecting the old rows.
    """
    canon = str(Path(root).expanduser().resolve())
    with write_tx() as conn:
        row = conn.execute("SELECT id FROM books WHERE dir = ?", (canon,)).fetchone()
        if not row:
            return False
        book_id = row["id"]
        for table in _BOOK_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        return True


def reset() -> None:
    """Test-only: drop the database file so each test starts clean."""
    with _WRITE_LOCK:
        _ready.clear()
        path = db_path()
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(path) + suffix).unlink()
            except FileNotFoundError:
                pass
