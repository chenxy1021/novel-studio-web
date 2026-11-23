"""Append-only JSONL ledgers with fold-on-read.

A damaged line never aborts the read: it comes back as {"__corrupt": True, "line": n, "raw": ...}
so callers (and the repair flow) can see it, exactly like io.js readJsonl.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from .fsatomic import atomic_write


def read_jsonl(file: str | os.PathLike) -> list[dict[str, Any]]:
    p = Path(file)
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8")
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


def append_jsonl(file: str | os.PathLike, record: dict[str, Any]) -> None:
    p = Path(file)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


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
    """Mirror domain.js foldForeshadow: op=payoff → paid, op=abandon → abandoned."""

    def apply(cur: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
        op = r.get("op")
        status = "paid" if op == "payoff" else "abandoned" if op == "abandon" else cur.get("status", "open")
        merged = {
            "id": r.get("id"),
            "name": (r.get("name") if r.get("name") is not None else cur.get("name")),
            "plantedChapter": (r.get("plantedChapter") if r.get("plantedChapter") is not None else cur.get("plantedChapter")),
            "dueChapter": (r.get("dueChapter") if r.get("dueChapter") is not None else cur.get("dueChapter")),
            "status": status,
        }
        for k in ("payoffChapter", "note", "kind", "source", "plantBeat", "revealWho", "revealChange", "hint", "abandon"):
            merged[k] = r.get(k) if r.get(k) not in (None, "") else cur.get(k)
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
