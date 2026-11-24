"""Book ledgers live in SQLite; JSONL files are audit/export snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from app.store import export_ledgers, read_jsonl, rebuild_ledgers
from app.store.jsonl import append_jsonl


def _book(tmp_path: Path, name: str = "书") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"title": name}, ensure_ascii=False), encoding="utf-8")
    return root


def test_first_read_imports_then_db_wins(tmp_path):
    root = _book(tmp_path)
    ledger = root / "ledger" / "foreshadow.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"id": "a", "v": 1}\n{"id": "b", "v": 2}\n', encoding="utf-8")

    assert [r["id"] for r in read_jsonl(ledger)] == ["a", "b"]

    # Manual file edits are ignored once the DB owns this ledger.
    ledger.write_text('{"id": "c", "v": 3}\n', encoding="utf-8")
    assert [r["id"] for r in read_jsonl(ledger)] == ["a", "b"]


def test_append_is_visible_and_kept_in_audit_file(tmp_path):
    root = _book(tmp_path)
    ledger = root / "ledger" / "outline.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"chapter": 1}\n', encoding="utf-8")

    append_jsonl(ledger, {"chapter": 2})
    append_jsonl(ledger, {"chapter": 3})

    assert [r["chapter"] for r in read_jsonl(ledger)] == [1, 2, 3]
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [json.loads(line)["chapter"] for line in lines] == [1, 2, 3]


def test_rebuild_adopts_file_after_manual_change(tmp_path):
    root = _book(tmp_path)
    ledger = root / "ledger" / "timeline.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"chapter": 1}\n', encoding="utf-8")
    assert [r["chapter"] for r in read_jsonl(ledger)] == [1]

    ledger.write_text('{"chapter": 2}\n{"chapter": 3}\n', encoding="utf-8")
    assert [r["chapter"] for r in read_jsonl(ledger)] == [1]  # DB still wins

    counts = rebuild_ledgers(root)
    assert counts == {"ledger/timeline.jsonl": 2}
    assert [r["chapter"] for r in read_jsonl(ledger)] == [2, 3]


def test_two_books_do_not_share_ledgers(tmp_path):
    a = _book(tmp_path, "甲")
    b = _book(tmp_path, "乙")
    for root, ids in ((a, ["a1", "a2"]), (b, ["b1"])):
        ledger = root / "ledger" / "foreshadow.jsonl"
        ledger.parent.mkdir()
        ledger.write_text("".join(json.dumps({"id": i}) + "\n" for i in ids), encoding="utf-8")

    assert [r["id"] for r in read_jsonl(a / "ledger" / "foreshadow.jsonl")] == ["a1", "a2"]
    assert [r["id"] for r in read_jsonl(b / "ledger" / "foreshadow.jsonl")] == ["b1"]

    append_jsonl(a / "ledger" / "foreshadow.jsonl", {"id": "a3"})
    assert [r["id"] for r in read_jsonl(a / "ledger" / "foreshadow.jsonl")] == ["a1", "a2", "a3"]
    assert [r["id"] for r in read_jsonl(b / "ledger" / "foreshadow.jsonl")] == ["b1"]


def test_export_rebuilds_files_from_db(tmp_path):
    root = _book(tmp_path)
    segments = root / "ledger" / "segments.jsonl"
    segments.parent.mkdir()
    segments.write_text('{"from": 1, "to": 10}\n', encoding="utf-8")
    assert len(read_jsonl(segments)) == 1
    append_jsonl(segments, {"from": 11, "to": 20})

    segments.unlink()
    counts = export_ledgers(root)
    assert counts["ledger/segments.jsonl"] == 2
    rows = [json.loads(line) for line in segments.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [(r["from"], r["to"]) for r in rows] == [(1, 10), (11, 20)]
    # Reading the exported file returns the same DB rows.
    assert [r["from"] for r in read_jsonl(segments)] == [1, 11]


def test_metrics_ledger_uses_db_too(tmp_path):
    root = _book(tmp_path)
    usage = root / "metrics" / "usage.jsonl"
    usage.parent.mkdir()
    usage.write_text('{"at": "t1", "kind": "prose"}\n', encoding="utf-8")

    assert read_jsonl(usage)[0]["kind"] == "prose"
    usage.write_text("", encoding="utf-8")
    assert read_jsonl(usage)[0]["kind"] == "prose"


def test_empty_and_corrupt_rows(tmp_path):
    root = _book(tmp_path)
    empty = root / "ledger" / "review.jsonl"
    empty.parent.mkdir()
    empty.write_text("", encoding="utf-8")
    assert read_jsonl(empty) == []

    damaged = root / "ledger" / "memory.jsonl"
    damaged.write_text('{"chapter": 1}\nnot json\n{"chapter": 2}\n', encoding="utf-8")
    rows = read_jsonl(damaged)
    assert rows[0] == {"chapter": 1}
    assert rows[1]["__corrupt"] is True
    assert rows[1]["line"] == 2
    assert rows[1]["raw"] == "not json"
    assert rows[2] == {"chapter": 2}

    # Corrupt marker survives the DB round-trip and rebuild/export.
    counts = rebuild_ledgers(root)
    assert counts["ledger/memory.jsonl"] == 3
    again = read_jsonl(damaged)
    assert again[1]["__corrupt"] is True
    export_ledgers(root)
    assert "not json" in damaged.read_text(encoding="utf-8")
