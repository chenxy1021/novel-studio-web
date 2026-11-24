"""API-facing book directory resolution: list books, validate one, recent books."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..store import chapter as chapter_store
from ..store import load_project
from ..store.paths import (
    DEFAULT_PROJECTS_DIR,
    assert_browsable_root,
    is_project,
    list_project_dirs,
)

RECENT_FILE = Path(
    os.environ.get("DSH_NOVEL_RECENT_FILE")
    or Path.home() / ".dsh" / "novel-studio" / "recent.json"
)


def books_root() -> Path:
    return DEFAULT_PROJECTS_DIR


def book_summary(dir: Path) -> dict[str, Any]:
    project = load_project(dir) or {}
    try:
        index = chapter_store.read_index(dir)
    except ValueError:
        index = []
    return {
        "dir": str(dir),
        "title": project.get("title") or dir.name,
        "genre": project.get("genre") or "",
        "targetChapters": project.get("targetChapters") or 0,
        "currentChapter": project.get("currentChapter") or 0,
        "chapterCount": len(index),
        "updatedAt": project.get("updatedAt") or "",
    }


def list_books() -> list[dict[str, Any]]:
    base = books_root()
    if not base.exists():
        return []
    return [book_summary(p) for p in list_project_dirs(base)]


def recent_books(limit: int = 5) -> list[dict[str, Any]]:
    try:
        data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for row in (data.get("projects") or [])[:limit]:
        d = Path(str(row.get("dir") or ""))
        if d.is_dir() and is_project(d):
            out.append({**book_summary(d), "openedAt": row.get("at") or ""})
    return out


def resolve_book(dir: str) -> Path:
    """Validate a book dir the panel is allowed to open; rejects system dirs and non-books."""
    if not dir:
        raise ValueError("缺少 dir 参数")
    p = assert_browsable_root(dir)
    if not p.is_dir():
        raise FileNotFoundError(f"目录不存在：{p}")
    if not is_project(p):
        raise ValueError(f"不是一个小说项目目录（缺少 project.json）：{p}")
    return p


def delete_book(dir: str, *, expect_title: str) -> Path:
    """永久删除整本书目录。

    需要调用方传入书名做二次确认：确认文字与 project.json 里的 title 不一致就拒绝，
    避免脚本或误点把书删掉。删除后不进回收站，无法从应用内恢复。
    """
    p = resolve_book(dir)
    project = load_project(p) or {}
    title = str(project.get("title") or p.name)
    if str(expect_title or "").strip() != title:
        raise ValueError(f"确认文字与书名不一致（书名为「{title}」）")

    if p == books_root().resolve() or p == Path.home().resolve():
        raise ValueError("拒绝删除书架根目录或家目录")
    if p.name.startswith("."):
        raise ValueError("拒绝删除隐藏目录")

    shutil.rmtree(p)
    # The directory is gone; drop its DB rows too, otherwise recreating a book
    # at the same path would resurrect the old settings and ledgers.
    try:
        from .. import db

        db.delete_book_data(p)
    except Exception:  # pragma: no cover - DB cleanup must not fail the delete
        pass
    return p
