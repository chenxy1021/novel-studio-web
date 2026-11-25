"""Append-only JSONL ledgers with fold-on-read.

Inside a book (``<root>/ledger/*.jsonl`` or ``<root>/metrics/*.jsonl``) the
SQLite ``ledger`` table is authoritative; the JSONL file is kept as an audit /
export copy. Paths outside a book keep the plain file semantics.

A damaged line never aborts the read: it comes back as
``{"__corrupt": True, "line": n, "raw": ...}`` so callers (and the repair flow)
can see it, exactly like io.js readJsonl. Corrupt lines are imported into the DB
as those same marker rows.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from .. import db
from .fsatomic import atomic_write

log = logging.getLogger(__name__)

_LEDGER_DIRS = ("ledger", "metrics")


# --------------------------------------------------------------------------- #
# Book-ledger routing
# --------------------------------------------------------------------------- #


def _book_id(root: Path) -> str | None:
    """Book id for a directory, importing project.json on first use (never raises)."""
    from .project import book_id_for

    try:
        return book_id_for(root)
    except (OSError, ValueError, sqlite3.Error):
        log.warning("无法解析账本所属的书：%s", root, exc_info=True)
        return None


def _resolve_book(file: str | os.PathLike) -> tuple[Path, str, str] | None:
    """(root, kind, book_id) when the path is a ledger inside a known book."""
    p = Path(file)
    if p.parent.name not in _LEDGER_DIRS:
        return None
    root = p.parent.parent
    kind = f"{p.parent.name}/{p.name}"
    book_id = _book_id(root)
    if book_id is None:
        return None
    return root, kind, book_id


def _rows_for(conn: sqlite3.Connection, book_id: str, kind: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT seq, data_json FROM ledger WHERE book_id = ? AND kind = ? ORDER BY seq",
        (book_id, kind),
    ).fetchall()


def _decode_one(raw: Any, seq: int) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"__corrupt": True, "line": seq, "raw": str(raw)}
    return value if isinstance(value, dict) else None


def _decode_rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        value = _decode_one(row["data_json"], int(row["seq"]))
        if value is not None:
            out.append(value)
    return out


def _parse_lines(raw: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, line in enumerate(raw.split("\n")):
        text = line.strip()
        if not text:
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            out.append({"__corrupt": True, "line": i + 1, "raw": text})
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _read_file_rows(file: str | os.PathLike) -> list[dict[str, Any]]:
    p = Path(file)
    if not p.exists():
        return []
    return _parse_lines(p.read_text(encoding="utf-8"))


def _import_file_rows(conn: sqlite3.Connection, book_id: str, kind: str, file: str | os.PathLike) -> int:
    rows = _read_file_rows(file)
    now = db.now_iso()
    for seq, row in enumerate(rows, 1):
        conn.execute(
            "INSERT OR IGNORE INTO ledger(book_id, kind, seq, data_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            (book_id, kind, seq, json.dumps(row, ensure_ascii=False), now),
        )
    return len(rows)


def _append_file(file: str | os.PathLike, record: dict[str, Any]) -> None:
    p = Path(file)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


# --------------------------------------------------------------------------- #
# Public JSONL API
# --------------------------------------------------------------------------- #


def read_jsonl(file: str | os.PathLike) -> list[dict[str, Any]]:
    ctx = _resolve_book(file)
    if ctx is None:
        return _read_file_rows(file)

    _, kind, book_id = ctx
    with db.read_conn() as conn:
        rows = _rows_for(conn, book_id, kind)
    if rows:
        return _decode_rows(rows)

    path = Path(file)
    if not path.exists():
        return []

    # First sight of this ledger: import the file once, then DB is authoritative.
    with db.write_tx() as conn:
        rows = _rows_for(conn, book_id, kind)
        if rows:
            return _decode_rows(rows)
        _import_file_rows(conn, book_id, kind, path)
        rows = _rows_for(conn, book_id, kind)
    return _decode_rows(rows)


def append_jsonl(file: str | os.PathLike, record: dict[str, Any]) -> None:
    ctx = _resolve_book(file)
    if ctx is None:
        _append_file(file, record)
        return

    _, kind, book_id = ctx
    path = Path(file)
    payload = json.dumps(record, ensure_ascii=False)

    last_error: sqlite3.IntegrityError | None = None
    for _attempt in range(2):  # one retry if another writer grabbed the seq
        try:
            with db.write_tx() as conn:
                if not _rows_for(conn, book_id, kind):
                    _import_file_rows(conn, book_id, kind, path)
                seq = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM ledger WHERE book_id = ? AND kind = ?",
                    (book_id, kind),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO ledger(book_id, kind, seq, data_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (book_id, kind, int(seq), payload, db.now_iso()),
                )
            last_error = None
            break
        except sqlite3.IntegrityError as e:
            last_error = e
    if last_error is not None:
        raise last_error

    try:
        _append_file(path, record)
    except OSError:
        log.warning("账本已写入 DB，但文件审计副本追加失败：%s", path, exc_info=True)


def rebuild_ledgers(root: str | os.PathLike) -> dict[str, int]:
    """Clear this book's ledger rows and re-import ``ledger/*.jsonl`` / ``metrics/*.jsonl``."""
    root_path = Path(os.path.abspath(str(root)))
    book_id = _book_id(root_path)
    if book_id is None:
        raise ValueError(f"不是小说项目或尚未导入：{root}")

    files = sorted(
        [*root_path.glob("ledger/*.jsonl"), *root_path.glob("metrics/*.jsonl")],
        key=lambda p: p.relative_to(root_path).as_posix(),
    )
    counts: dict[str, int] = {}
    with db.write_tx() as conn:
        conn.execute("DELETE FROM ledger WHERE book_id = ?", (book_id,))
        for path in files:
            kind = path.relative_to(root_path).as_posix()
            counts[kind] = _import_file_rows(conn, book_id, kind, path)
    return counts


def export_ledgers(root: str | os.PathLike) -> dict[str, int]:
    """Rewrite the JSONL audit files from the DB (atomic replace)."""
    root_path = Path(os.path.abspath(str(root)))
    book_id = _book_id(root_path)
    if book_id is None:
        raise ValueError(f"不是小说项目或尚未导入：{root}")

    with db.read_conn() as conn:
        kinds = [
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT kind FROM ledger WHERE book_id = ? ORDER BY kind", (book_id,)
            ).fetchall()
        ]
        per_kind = {kind: _rows_for(conn, book_id, kind) for kind in kinds}

    counts: dict[str, int] = {}
    for kind, rows in per_kind.items():
        lines: list[str] = []
        for row in rows:
            value = _decode_one(row["data_json"], int(row["seq"]))
            if value is None:
                continue
            if is_corrupt(value) and value.get("raw") is not None:
                lines.append(str(value["raw"]))
            else:
                lines.append(json.dumps(value, ensure_ascii=False))
        atomic_write(root_path / kind, ("\n".join(lines) + "\n") if lines else "")
        counts[kind] = len(lines)
    return counts


# --------------------------------------------------------------------------- #
# Fold helpers (unchanged)
# --------------------------------------------------------------------------- #


def is_corrupt(row: Any) -> bool:
    return isinstance(row, dict) and row.get("__corrupt") is True


def fold_by_key(
    rows: Iterable[dict[str, Any]],
    key_field: str,
    apply: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Fold events on ``key_field``: later rows win; ``apply`` may merge or return None to drop."""
    current: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if is_corrupt(row) or not isinstance(row, dict):
            continue
        key = row.get(key_field)
        if key in (None, ""):
            continue
        if apply is None:
            current[key] = row
            continue
        merged = apply(current.get(key, {}), row)
        if merged is None:
            current.pop(key, None)
        else:
            current[key] = merged
    return list(current.values())


def _num(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def fold_foreshadow(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror domain.js foldForeshadow: op=payoff → paid, op=abandon → abandoned, op=reopen → open."""

    def apply(cur: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
        op = r.get("op")
        status = (
            "paid" if op == "payoff"
            else "abandoned" if op == "abandon"
            else "open" if op == "reopen"
            else cur.get("status", "open")
        )
        merged = {
            "id": r.get("id"),
            "name": (r.get("name") if r.get("name") is not None else cur.get("name")),
            "plantedChapter": (r.get("plantedChapter") if r.get("plantedChapter") is not None else cur.get("plantedChapter")),
            "dueChapter": (r.get("dueChapter") if r.get("dueChapter") is not None else cur.get("dueChapter")),
            "status": status,
        }
        for k in ("payoffChapter", "note", "kind", "source", "plantBeat", "revealWho", "revealChange", "hint", "abandon"):
            merged[k] = r.get(k) if r.get(k) not in (None, "") else cur.get(k)
        if op == "reopen":
            # 重新打开就是「当它没收过」：收线章一起清掉，否则面板会同时显示未收和收在几章。
            merged["payoffChapter"] = None
        merged["lastAt"] = r.get("at")
        return merged

    return fold_by_key(rows, "id", apply)


def fold_segments(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror segment.js foldSegments: same from-to last wins, op=delete removes, sorted."""
    current: dict[str, dict[str, Any]] = {}
    for r in rows:
        if is_corrupt(r) or not isinstance(r, dict):
            continue
        f, t = _num(r.get("from")), _num(r.get("to"))
        if not f or t < f:
            continue
        key = f"{f}-{t}"
        if r.get("op") == "delete":
            current.pop(key, None)
            continue
        if not r.get("plan"):
            continue
        current[key] = {**r, "from": f, "to": t}
    return sorted(current.values(), key=lambda s: (s["from"], s["to"]))


def fold_outline(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """ledger/outline.jsonl: one row per chapter; deleted:true drops it; chapter==0 is volume-level."""
    current: dict[int, dict[str, Any]] = {}
    for r in rows:
        if is_corrupt(r) or not isinstance(r, dict):
            continue
        n = _num(r.get("chapter"))
        if r.get("deleted"):
            current.pop(n, None)
        else:
            current[n] = {**r, "chapter": n}
    return [current[k] for k in sorted(current)]


def fold_timeline(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(fold_by_key(rows, "chapter"), key=lambda r: _num(r.get("chapter")))


def fold_dismissed(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return fold_by_key(rows, "key")


def fold_review(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """review.jsonl is an event stream (discard/purge/restore); callers decide. Return good rows."""
    return [r for r in rows if isinstance(r, dict) and not is_corrupt(r)]


def corrupt_lines(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if is_corrupt(r)]


def rewrite_clean_jsonl(file: str | os.PathLike, rows: Sequence[dict[str, Any]]) -> int:
    """Drop corrupt rows, atomically rewrite the file. Returns removed count (for repair)."""
    keep = [json.dumps(r, ensure_ascii=False) for r in rows if not is_corrupt(r)]
    removed = sum(1 for r in rows if is_corrupt(r))
    if removed:
        atomic_write(file, ("\n".join(keep) + "\n") if keep else "")
    return removed
