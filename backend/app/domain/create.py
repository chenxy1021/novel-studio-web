"""新书脚手架：把「选题」表单落成一个工作台能直接打开的书目录。

只写最小可用的文件：project.json / bible.json / chapters/index.json，
以及空的 ledger 账本。分卷、人物、段落纲留给作者在页面里继续补。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.paths import book_summary, books_root
from ..store import (
    assert_writable_root,
    ensure_dir,
    project_path,
    save_bible,
    save_project,
    write_index,
    write_text,
)
from .platforms import PLATFORMS, PLAYBOOKS, platform_rules

LEDGER_FILES = (
    "ledger/foreshadow.jsonl",
    "ledger/segments.jsonl",
    "ledger/timeline.jsonl",
    "ledger/outline.jsonl",
    "ledger/memory.jsonl",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_dir_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title).strip().strip(".")
    name = re.sub(r"\s+", " ", name)[:60].strip()
    return name or "未命名"


def _unique_dir(base: Path, name: str) -> Path:
    target = base / name
    n = 2
    while target.exists():
        target = base / f"{name}-{n}"
        n += 1
    return target


def list_platforms() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "wordsMin": p["wordsMin"],
            "wordsMax": p["wordsMax"],
            "dialogueMin": p["dialogueMin"],
            "short": bool(p.get("short")),
            "reader": PLAYBOOKS.get(p["id"], PLAYBOOKS["generic"])["reader"],
            "opening": PLAYBOOKS.get(p["id"], PLAYBOOKS["generic"])["opening"],
            "rhythm": PLAYBOOKS.get(p["id"], PLAYBOOKS["generic"])["rhythm"],
        }
        for p in PLATFORMS.values()
    ]


def create_book(
    *,
    title: str,
    genre: str = "",
    platform: str = "generic",
    target_chapters: int = 100,
    words_per_chapter: int = 0,
    logline: str = "",
    synopsis: str = "",
    theme: str = "",
    tone: str = "",
    concepts: list[dict[str, Any]] | None = None,
    selected_concept_id: str = "",
    nuewen: bool = False,
) -> dict[str, Any]:
    label = title.strip()
    if not label:
        raise ValueError("书名不能为空")
    if len(label) > 60:
        raise ValueError("书名最多 60 个字")

    rules = platform_rules(platform)
    target = int(target_chapters or 0)
    if target <= 0:
        target = 100
    if target > 5000:
        raise ValueError("目标章数最多 5000")
    words = int(words_per_chapter or 0)
    if words <= 0:
        words = rules["wordsMin"]

    base = books_root()
    ensure_dir(base)
    dest = _unique_dir(base, _safe_dir_name(label))
    assert_writable_root(dest, creating=True)

    now = _now()
    ensure_dir(dest)
    ensure_dir(dest / "chapters")
    ensure_dir(dest / "ledger")
    ensure_dir(dest / "drafts")
    ensure_dir(dest / "metrics")

    project = {
        "title": label,
        "genre": genre.strip(),
        "platform": rules["name"],
        "logline": logline.strip(),
        "synopsis": synopsis.strip(),
        "theme": theme.strip(),
        "tone": tone.strip(),
        "spine": theme.strip() or logline.strip(),
        "targetChapters": target,
        "currentChapter": 0,
        "wordsPerChapter": words,
        "gate": {
            "phase": "planning",
            "chapter": 1,
            "reason": "新书开张：先分卷，再定第一段 10 章段落纲",
            "at": now,
        },
        "gates": {},
        "createdAt": now,
        "updatedAt": now,
    }
    if nuewen:
        # 选题阶段就勾了虐文：把改写/复检要用的虐文模式一并打开。
        project["nuewen"] = True
    # 选题候选留着，之后补大纲/设定时还能回看当初为什么开这本书。
    rows = [c for c in (concepts or []) if isinstance(c, dict)][:10]
    if rows:
        project["concepts"] = rows
        if selected_concept_id:
            project["selectedConceptId"] = selected_concept_id
            chosen = next((c for c in rows if str(c.get("id") or "") == selected_concept_id), None)
            if chosen:
                project["concept"] = chosen
    save_project(dest, project)

    style: dict[str, Any] = {}
    if tone.strip():
        style["notes"] = tone.strip()
    save_bible(dest, {
        "characters": [], "world": [], "rules": [], "factions": [],
        "locations": [], "items": [], "relations": [], "infoGaps": [],
        "style": style,
    })

    write_index(dest, [])
    for rel in LEDGER_FILES:
        write_text(project_path(dest, rel), "")

    return book_summary(dest)
