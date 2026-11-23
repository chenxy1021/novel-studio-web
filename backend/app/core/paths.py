"""API-facing book directory resolution: list books, validate one, recent books."""

from __future__ import annotations

import json
import os
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
