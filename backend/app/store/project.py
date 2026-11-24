"""DB-authoritative project/bible storage + JSON snapshots.

``studio.db`` (see :mod:`app.db`) is the source of truth for the mutable book
settings. ``project.json`` / ``bible.json`` are written back as compatibility
snapshots for the legacy plugin, and read only on first import / explicit
``rebuild_book``.

Body text, chapter index, ledgers, prompts and templates remain files.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .. import db
from .fsatomic import atomic_write
from .paths import LAYOUT, project_path

BIBLE_DEFAULTS: dict[str, Any] = {
    "characters": [],
    "world": [],
    "rules": [],
    "style": {},
    "factions": [],
    "locations": [],
    "items": [],
    "relations": [],
    "infoGaps": [],
}


def read_json(file: str | os.PathLike, fallback: Any = ...) -> Any:
    try:
        return json.loads(Path(file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if fallback is not ...:
            return copy.deepcopy(fallback)
        raise
    except json.JSONDecodeError as e:
        raise ValueError(f"读取失败 {file}: {e}") from e


def write_json(file: str | os.PathLike, value: Any) -> Path:
    return atomic_write(file, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_text(file: str | os.PathLike) -> str:
    return Path(file).read_text(encoding="utf-8")


def write_text(file: str | os.PathLike, text: str) -> Path:
    return atomic_write(file, text)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _canon(root: str | os.PathLike) -> str:
    """Stable key for ``books.dir`` (resolves symlinks / ``..``)."""
    return os.path.realpath(os.path.abspath(str(root)))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_obj(raw: Any, label: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"{label} 损坏：{e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{label} 不是对象")
    return data


def _find_book(conn: sqlite3.Connection, canon: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, data_json FROM books WHERE dir = ?", (canon,)).fetchone()


def _row_data(row: sqlite3.Row) -> dict[str, Any]:
    data = _parse_obj(row["data_json"], "books.data_json")
    if not data.get("id"):
        data = {**data, "id": str(row["id"])}
    return data


def _read_file_obj(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 不是对象：{path}")
    return data


def _bible_shape(data: Any) -> dict[str, Any]:
    """Always return the shape domain code expects; unknown keys survive."""
    base = copy.deepcopy(BIBLE_DEFAULTS)
    if isinstance(data, dict):
        base.update(data)
    return base


def _import_book(conn: sqlite3.Connection, root: str | os.PathLike, canon: str) -> tuple[str, dict[str, Any]] | None:
    """First-time import from project.json. Returns None when the file is absent."""
    data = _read_file_obj(project_path(root, LAYOUT["project"]))
    if data is None:
        return None
    book_id = str(data.get("id") or "").strip()
    if not book_id:
        book_id = str(uuid.uuid4())
    clash = conn.execute("SELECT dir FROM books WHERE id = ?", (book_id,)).fetchone()
    if clash is not None and str(clash["dir"]) != canon:
        book_id = str(uuid.uuid4())
    imported = {**data, "id": book_id}
    now = db.now_iso()
    conn.execute(
        "INSERT INTO books(id, dir, title, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            book_id,
            canon,
            str(imported.get("title") or ""),
            _dump(imported),
            str(imported.get("createdAt") or now),
            str(imported.get("updatedAt") or now),
        ),
    )
    return book_id, imported


def _upsert_book(
    conn: sqlite3.Connection,
    book_id: str,
    canon: str,
    data: dict[str, Any],
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO books(id, dir, title, data_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            dir = excluded.dir,
            title = excluded.title,
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        (
            book_id,
            canon,
            str(data.get("title") or ""),
            _dump(data),
            str(data.get("createdAt") or now),
            str(data.get("updatedAt") or now),
        ),
    )


def _insert_empty_book(conn: sqlite3.Connection, canon: str, root: str | os.PathLike) -> str:
    """Row for a directory that has no project.json yet (only used by save_bible)."""
    book_id = str(uuid.uuid4())
    now = db.now_iso()
    name = Path(os.path.abspath(str(root))).name
    conn.execute(
        "INSERT INTO books(id, dir, title, data_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (book_id, canon, name, "{}", now, now),
    )
    return book_id


def _upsert_bible(conn: sqlite3.Connection, book_id: str, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO bible(book_id, data_json, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(book_id) DO UPDATE SET
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        (book_id, _dump(data), db.now_iso()),
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def load_project(root: str | os.PathLike) -> dict[str, Any]:
    """DB value for this directory, importing project.json on first sight.

    Returns ``{}`` when neither the DB nor project.json knows the book (no row is
    created in that case), matching the callers that use ``load_project(root) or {}``.
    """
    canon = _canon(root)
    with db.read_conn() as conn:
        row = _find_book(conn, canon)
        if row is not None:
            return _row_data(row)

    with db.write_tx() as conn:
        row = _find_book(conn, canon)
        if row is not None:
            return _row_data(row)
        imported = _import_book(conn, root, canon)
    return imported[1] if imported is not None else {}


def save_project(root: str | os.PathLike, project: dict[str, Any]) -> Path:
    """Upsert the DB row (merging over existing keys) and refresh project.json."""
    if not isinstance(project, dict):
        raise ValueError("project 必须是对象")
    incoming = copy.deepcopy(project)
    canon = _canon(root)

    with db.write_tx() as conn:
        row = _find_book(conn, canon)
        if row is not None:
            book_id = str(row["id"])
            merged = {**(_row_data(row)), **incoming}
        else:
            book_id = str(incoming.get("id") or "").strip()
            if not book_id or conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                book_id = str(uuid.uuid4())
            merged = incoming
        merged["id"] = book_id
        _upsert_book(conn, book_id, canon, merged, db.now_iso())

    return write_json(project_path(root, LAYOUT["project"]), merged)


def load_bible(root: str | os.PathLike) -> dict[str, Any]:
    """Always returns the shape domain code expects, even for old books missing keys."""
    canon = _canon(root)

    with db.read_conn() as conn:
        book = _find_book(conn, canon)
        if book is not None:
            row = conn.execute("SELECT data_json FROM bible WHERE book_id = ?", (book["id"],)).fetchone()
            if row is not None:
                return _bible_shape(_parse_obj(row["data_json"], "bible.data_json"))

    # No DB row yet: import project.json first (that is what creates the book row).
    if book is None:
        with db.write_tx() as conn:
            book = _find_book(conn, canon)
            if book is None and _import_book(conn, root, canon) is not None:
                book = _find_book(conn, canon)
        if book is None:
            # Directory without project.json: legacy file-only behaviour, no row.
            return _bible_shape(_read_file_obj(project_path(root, LAYOUT["bible"])))

    data = _read_file_obj(project_path(root, LAYOUT["bible"]))
    if data is None:
        return _bible_shape(None)

    with db.write_tx() as conn:
        existing = conn.execute("SELECT data_json FROM bible WHERE book_id = ?", (book["id"],)).fetchone()
        if existing is not None:
            return _bible_shape(_parse_obj(existing["data_json"], "bible.data_json"))
        _upsert_bible(conn, str(book["id"]), data)
    return _bible_shape(data)


def save_bible(root: str | os.PathLike, bible: dict[str, Any]) -> Path:
    if not isinstance(bible, dict):
        raise ValueError("bible 必须是对象")
    data = copy.deepcopy(bible)
    canon = _canon(root)

    with db.write_tx() as conn:
        book = _find_book(conn, canon)
        if book is None:
            imported = _import_book(conn, root, canon)
            book_id = imported[0] if imported is not None else _insert_empty_book(conn, canon, root)
        else:
            book_id = str(book["id"])
        _upsert_bible(conn, book_id, data)

    return write_json(project_path(root, LAYOUT["bible"]), data)


def rebuild_book(root: str | os.PathLike) -> dict[str, Any]:
    """Force re-import project.json / bible.json over the DB, keeping the book id."""
    canon = _canon(root)
    data = _read_file_obj(project_path(root, LAYOUT["project"]))
    if data is None:
        raise FileNotFoundError(f"缺少 project.json，无法重建：{project_path(root, LAYOUT['project'])}")
    bible_data = _read_file_obj(project_path(root, LAYOUT["bible"]))

    with db.write_tx() as conn:
        row = _find_book(conn, canon)
        if row is not None:
            book_id = str(row["id"])
        else:
            book_id = str(data.get("id") or "").strip()
            if not book_id or conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone():
                book_id = str(uuid.uuid4())
        merged = {**data, "id": book_id}
        _upsert_book(conn, book_id, canon, merged, db.now_iso())
        if bible_data is not None:
            _upsert_bible(conn, book_id, bible_data)
        else:
            conn.execute("DELETE FROM bible WHERE book_id = ?", (book_id,))
    return merged


def export_snapshot(root: str | os.PathLike) -> tuple[Path, Path]:
    """Write project.json / bible.json back from the DB (no file reads)."""
    canon = _canon(root)
    with db.read_conn() as conn:
        row = _find_book(conn, canon)
        if row is None:
            raise ValueError(f"DB 里没有这本书，无法导出快照：{root}")
        book_id = str(row["id"])
        project = _row_data(row)
        brow = conn.execute("SELECT data_json FROM bible WHERE book_id = ?", (book_id,)).fetchone()

    project = {**project, "id": book_id}
    bible = (
        _bible_shape(_parse_obj(brow["data_json"], "bible.data_json"))
        if brow is not None
        else _bible_shape(None)
    )
    return (
        write_json(project_path(root, LAYOUT["project"]), project),
        write_json(project_path(root, LAYOUT["bible"]), bible),
    )


def book_id_for(root: str | os.PathLike) -> str | None:
    """DB id for the book at ``root``; imports project.json first when needed."""
    canon = _canon(root)
    with db.read_conn() as conn:
        row = _find_book(conn, canon)
        if row is not None:
            return str(row["id"])
    project = load_project(root)
    return str(project.get("id") or "") or None
