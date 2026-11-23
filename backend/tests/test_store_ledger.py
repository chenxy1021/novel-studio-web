"""JSONL append + fold read, including the damaged-last-line rule."""

from __future__ import annotations

from app.store.jsonl import (
    append_jsonl,
    corrupt_lines,
    fold_by_key,
    fold_foreshadow,
    fold_outline,
    fold_segments,
    read_jsonl,
    rewrite_clean_jsonl,
)


def test_corrupt_last_line_is_skipped_not_fatal(tmp_path):
    f = tmp_path / "ledger" / "x.jsonl"
    append_jsonl(f, {"id": "a", "v": 1})
    with open(f, "a", encoding="utf-8") as fh:
        fh.write('{"id": "b", "v": ')
    rows = read_jsonl(f)
    assert rows[0] == {"id": "a", "v": 1}
    assert corrupt_lines(rows)[0]["line"] == 2
    assert len(fold_by_key(rows, "id")) == 1


def test_rewrite_clean_jsonl_drops_damaged_rows(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"id":1}\nnot json\n{"id":2}\n', encoding="utf-8")
    rows = read_jsonl(f)
    assert rewrite_clean_jsonl(f, rows) == 1
    assert [r["id"] for r in read_jsonl(f)] == [1, 2]


def test_append_never_rewrites_existing_lines(tmp_path):
    f = tmp_path / "x.jsonl"
    append_jsonl(f, {"id": 1})
    first = f.read_bytes()
    append_jsonl(f, {"id": 2})
    assert f.read_bytes().startswith(first)


def test_missing_file_reads_empty(tmp_path):
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_fold_foreshadow_plant_payoff_abandon():
    rows = [
        {"id": "f1", "op": "plant", "name": "旧账", "plantedChapter": 1, "dueChapter": 9, "status": "open"},
        {"id": "f1", "op": "payoff", "name": "旧账", "plantedChapter": 1, "dueChapter": 9, "payoffChapter": 7},
        {"id": "f2", "op": "plant", "name": "门", "plantedChapter": 2, "dueChapter": 5},
        {"id": "f2", "op": "abandon", "name": "门", "plantedChapter": 2, "dueChapter": 5},
    ]
    out = {f["id"]: f for f in fold_foreshadow(rows)}
    assert out["f1"]["status"] == "paid"
    assert out["f1"]["payoffChapter"] == 7
    assert out["f2"]["status"] == "abandoned"


def test_fold_segments_delete_and_overlap_rules():
    rows = [
        {"kind": "segment", "from": 1, "to": 10, "plan": {"stages": [1, 2, 3]}, "v": 1},
        {"kind": "segment", "from": 11, "to": 20, "plan": {"stages": [1]}},
        {"kind": "segment", "from": 1, "to": 10, "plan": {"stages": [1, 2, 3, 4]}, "v": 2},
        {"kind": "segment", "op": "delete", "from": 11, "to": 20},
        {"__corrupt": True, "line": 5, "raw": "{"},
    ]
    segs = fold_segments(rows)
    assert [(s["from"], s["to"]) for s in segs] == [(1, 10)]
    assert segs[0]["v"] == 2


def test_fold_outline_deleted_chapter_dropped():
    rows = [{"chapter": 0, "title": "全书层"}, {"chapter": 1, "beats": ["a"]}, {"chapter": 1, "deleted": True}]
    assert [r["chapter"] for r in fold_outline(rows)] == [0]


def test_utf8_roundtrip(tmp_path):
    f = tmp_path / "u.jsonl"
    append_jsonl(f, {"name": "季恒", "note": "两百兆赫"})
    assert read_jsonl(f)[0]["note"] == "两百兆赫"
    assert "季恒" in f.read_text(encoding="utf-8")
