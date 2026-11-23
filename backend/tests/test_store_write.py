"""Atomic writes, chapter index upsert, path escaping, project lock."""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from app.store import (
    add_to_index,
    chapter_file_path,
    ensure_chapter_dirs,
    project_lock,
    read_chapter,
    read_index,
    save_project,
    write_chapter,
    write_json,
)
from app.store.paths import assert_writable_root, safe_join


def make_book(tmp_path):
    root = tmp_path / "book"
    ensure_chapter_dirs(root)
    write_json(root / "chapters" / "index.json", [])
    save_project(root, {"version": 1, "title": "测试书", "targetChapters": 100})
    return root


def test_write_json_is_atomic_and_pretty(tmp_path):
    f = tmp_path / "a" / "project.json"
    write_json(f, {"title": "书"})
    assert f.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(f.read_text(encoding="utf-8"))["title"] == "书"
    assert not [p for p in f.parent.iterdir() if ".tmp-" in p.name]


def test_chapter_file_name_sanitized(tmp_path):
    p = chapter_file_path(tmp_path, 7, "谁在替我念？/第2话")
    assert p.name == "007-谁在替我念-第2话.md"
    assert chapter_file_path(tmp_path, 12, "!!!").name == "012-未命名.md"


def test_write_chapter_renames_and_removes_orphan(tmp_path):
    root = make_book(tmp_path)
    path1, rel1 = write_chapter(root, 1, "旧名", "正文。")
    add_to_index(root, {"number": 1, "title": "旧名", "file": rel1, "chars": 3})
    path2, rel2 = write_chapter(root, 1, "新名", "改过的正文。")
    add_to_index(root, {"number": 1, "title": "新名", "file": rel2, "chars": 6})
    assert not path1.exists()
    assert path2.exists()
    assert read_chapter(root, 1) == "改过的正文。\n"
    assert read_index(root)[0]["title"] == "新名"


def test_index_upsert_keeps_manual_fields(tmp_path):
    root = make_book(tmp_path)
    add_to_index(root, {"number": 2, "title": "二", "file": "chapters/002-二.md", "summary": "手写摘要"})
    add_to_index(root, {"number": 1, "title": "一", "file": "chapters/001-一.md"})
    add_to_index(root, {"number": 2, "chars": 2000, "approved": True})
    rows = read_index(root)
    assert [r["number"] for r in rows] == [1, 2]
    assert rows[1]["summary"] == "手写摘要"
    assert rows[1]["chars"] == 2000


def test_index_with_gaps_keeps_numbers(tmp_path):
    root = make_book(tmp_path)
    for n in (1, 5, 9):
        add_to_index(root, {"number": n, "title": str(n), "file": f"chapters/{n:03d}-x.md"})
    assert [r["number"] for r in read_index(root)] == [1, 5, 9]


def test_safe_join_blocks_escape(tmp_path):
    with pytest.raises(PermissionError):
        safe_join(tmp_path, "../etc/passwd")
    with pytest.raises(PermissionError):
        safe_join(tmp_path, "/etc/passwd")
    assert safe_join(tmp_path, "chapters/001.md") == tmp_path / "chapters" / "001.md"


def test_writable_root_rejects_system_and_relative():
    with pytest.raises(ValueError):
        assert_writable_root("relative/path", creating=True)
    with pytest.raises(PermissionError):
        assert_writable_root("/etc", creating=True)
    with pytest.raises(PermissionError):
        assert_writable_root("/Library", creating=True)


def test_writable_root_allows_configured_home(tmp_path):
    target = tmp_path / "新书"
    assert assert_writable_root(target, creating=True, extra_roots=[str(tmp_path)]) == target.resolve()


def test_lock_is_exclusive_across_threads(tmp_path):
    root = make_book(tmp_path)
    events: list[str] = []
    started = threading.Event()

    def worker():
        with project_lock(root):
            events.append("b-enter")
            started.set()
            time.sleep(0.15)
            events.append("b-exit")

    with project_lock(root):
        t = threading.Thread(target=worker)
        t.start()
        started.wait(timeout=0.05)
        events.append("a-exit-about-to")
    t.join(timeout=5)
    assert events == ["a-exit-about-to", "b-enter", "b-exit"]


def test_lock_reentrant(tmp_path):
    root = make_book(tmp_path)
    with project_lock(root):
        with project_lock(root):
            pass


def test_lock_file_is_stable_anchor(tmp_path):
    root = make_book(tmp_path)
    with project_lock(root):
        pass
    assert os.path.exists(root / ".novel-studio.lock")
