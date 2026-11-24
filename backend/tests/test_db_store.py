"""SQLite is the source of truth for project/bible; JSON files are snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from app import db
from app.store import (
    book_id_for,
    export_snapshot,
    load_bible,
    load_project,
    rebuild_book,
    save_bible,
    save_project,
)


def _write_book(
    tmp_path: Path,
    name: str = "书",
    project: dict | None = None,
    bible: dict | None = None,
) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps(project if project is not None else {"title": "测试书", "targetChapters": 10}, ensure_ascii=False),
        encoding="utf-8",
    )
    if bible is not None:
        (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    return root


def _snapshot(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_first_load_imports_and_generates_stable_id(tmp_path):
    root = _write_book(tmp_path, project={"title": "测试书", "targetChapters": 10, "custom": {"a": 1}})

    first = load_project(root)
    assert first["title"] == "测试书"
    assert first["custom"] == {"a": 1}
    assert first["id"]

    second = load_project(root)
    assert second == first
    assert book_id_for(root) == first["id"]

    with db.read_conn() as conn:
        rows = conn.execute("SELECT id, dir FROM books").fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["dir"] == str(root.resolve())


def test_missing_project_json_returns_empty_and_creates_no_row(tmp_path):
    root = tmp_path / "空目录"
    root.mkdir()

    assert load_project(root) == {}
    assert book_id_for(root) is None
    with db.read_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0


def test_db_wins_until_rebuild(tmp_path):
    root = _write_book(tmp_path, project={"title": "DB书名", "targetChapters": 10, "custom": {"a": 1}})
    first = load_project(root)

    # Editing the file behind the DB must not leak in.
    (root / "project.json").write_text(
        json.dumps({"title": "文件书名", "targetChapters": 20}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert load_project(root)["title"] == "DB书名"

    rebuilt = rebuild_book(root)
    assert rebuilt["title"] == "文件书名"
    assert rebuilt["targetChapters"] == 20
    assert rebuilt["id"] == first["id"]  # book id preserved
    assert "custom" not in rebuilt  # rebuild reflects the file, not the old DB row

    again = load_project(root)
    assert again["title"] == "文件书名"
    assert again["id"] == first["id"]


def test_save_project_keeps_unknown_fields_and_syncs_snapshot(tmp_path):
    root = _write_book(tmp_path, project={"title": "原", "targetChapters": 10, "custom": "keep"})
    project = load_project(root)
    project["title"] = "新"
    project["dbOnly"] = {"deep": [1, 2]}
    save_project(root, project)

    snap = _snapshot(root, "project.json")
    assert snap["title"] == "新"
    assert snap["id"] == project["id"]
    assert snap["custom"] == "keep"
    assert snap["dbOnly"] == {"deep": [1, 2]}

    # Partial save: existing keys survive, id does not change.
    save_project(root, {"title": "再改"})
    again = load_project(root)
    assert again["title"] == "再改"
    assert again["custom"] == "keep"
    assert again["dbOnly"] == {"deep": [1, 2]}
    assert again["id"] == project["id"]


def test_save_bible_writes_db_and_snapshot(tmp_path):
    root = _write_book(
        tmp_path,
        project={"title": "书"},
        bible={"characters": [{"name": "甲"}], "style": {"pov": "第一人称"}, "extra": "x"},
    )

    bible = load_bible(root)
    assert bible["rules"] == []  # defaults filled for old books
    assert bible["extra"] == "x"
    bible["characters"].append({"name": "乙"})
    save_bible(root, bible)

    snap = _snapshot(root, "bible.json")
    assert [c["name"] for c in snap["characters"]] == ["甲", "乙"]
    assert snap["extra"] == "x"

    assert [c["name"] for c in load_bible(root)["characters"]] == ["甲", "乙"]


def test_export_snapshot_rebuilds_files_from_db(tmp_path):
    root = _write_book(
        tmp_path,
        project={"title": "库名", "targetChapters": 7},
        bible={"characters": [{"name": "甲"}]},
    )
    load_project(root)
    load_bible(root)
    (root / "project.json").unlink()
    (root / "bible.json").unlink()

    project_path, bible_path = export_snapshot(root)
    assert project_path == root / "project.json"
    assert bible_path == root / "bible.json"

    project = _snapshot(root, "project.json")
    assert project["title"] == "库名"
    assert project["id"]
    bible = _snapshot(root, "bible.json")
    assert bible["characters"][0]["name"] == "甲"
    assert bible["style"] == {}


def test_two_books_do_not_share_rows(tmp_path):
    a = _write_book(tmp_path, "甲", {"title": "甲书"}, {"characters": [{"name": "甲角"}]})
    b = _write_book(tmp_path, "乙", {"title": "乙书"}, {"characters": [{"name": "乙角"}]})

    pa, pb = load_project(a), load_project(b)
    assert pa["id"] != pb["id"]
    assert load_bible(a)["characters"][0]["name"] == "甲角"
    assert load_bible(b)["characters"][0]["name"] == "乙角"

    pa["title"] = "甲改"
    save_project(a, pa)
    assert load_project(a)["title"] == "甲改"
    assert load_project(b)["title"] == "乙书"


def test_delete_book_data_drops_rows_so_same_path_starts_clean(tmp_path):
    root = _write_book(tmp_path, "删", {"title": "旧书"}, {"characters": [{"name": "旧角"}]})
    old = load_project(root)
    assert old["id"]

    assert db.delete_book_data(root) is True
    assert db.delete_book_data(root) is False

    (root / "bible.json").unlink()
    (root / "project.json").write_text(
        json.dumps({"title": "新书"}, ensure_ascii=False), encoding="utf-8"
    )
    fresh = load_project(root)
    assert fresh["title"] == "新书"
    assert fresh["id"] != old["id"]
    assert load_bible(root)["characters"] == []
