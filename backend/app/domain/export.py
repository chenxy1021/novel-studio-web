"""一键导出：把整本书排成一份纯 TXT。

只读正文，不改任何账本。导出件落在 ``exports/书名-时间.txt``，同时把文件名和
元信息返回给前端；浏览器下载走同一个生成函数，保证「导出的文件」和「下载的
文件」逐字一致。

排版约定：
- 开头是书名 + 一句话 + 题材，空一行后进正文；
- 每章一个标题行「第N章 标题」，正文原样保留（正文文件本身不带标题）；
- 章与章之间空两行，方便直接贴进任何编辑器或平台后台；
- 章序号按 ``chapters/index.json`` 的实际章号，缺章不补空章，但会提示断档。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from ..store import load_project, project_path, read_chapter, read_index
from ..store.fsatomic import atomic_write

_BAD_NAME = re.compile(r'[\\/:*?"<>|\s]+')


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_filename(name: str, fallback: str = "未命名") -> str:
    cleaned = _BAD_NAME.sub("_", _text(name)).strip("._")
    return (cleaned or fallback)[:60]


def chapter_heading(number: int, title: str) -> str:
    """文件里没写标题，导出时补一行；标题本身已经带「第N章」就不再重复。"""
    t = _text(title)
    if re.match(r"^第\s*[0-9一二三四五六七八九十百千零两]+\s*[章回节]", t):
        return t
    return f"第{number}章 {t}".strip()


def build_export(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root) or {}
    index = read_index(root)
    if not index:
        raise ValueError("这本书还没有任何章节，无法导出")

    title = _text(project.get("title")) or "未命名"
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"{safe_filename(title)}-{stamp}.txt"

    header: list[str] = [title]
    sub = "　".join(x for x in (_text(project.get("genre")), _text(project.get("logline"))) if x)
    if sub:
        header.append(sub)
    parts: list[str] = ["\n".join(header)]

    numbers: list[int] = []
    missing: list[int] = []
    empty: list[int] = []
    total_chars = 0
    for entry in index:
        n = _num(entry.get("number"))
        if n <= 0:
            continue
        try:
            body = read_chapter(root, n)
        except FileNotFoundError:
            missing.append(n)
            continue
        body = (body or "").strip()
        if not body:
            empty.append(n)
            continue
        numbers.append(n)
        total_chars += len(body)
        parts.append("\n".join([chapter_heading(n, str(entry.get("title") or "")), "", body]))

    if not parts[1:]:
        raise ValueError("所有章节正文都是空的，无法导出")

    gaps: list[str] = []
    for a, b in zip(numbers, numbers[1:]):
        if b > a + 1:
            gaps.append(f"{a + 1}-{b - 1}")
    expected = _num(project.get("targetChapters"))
    tail = f"（计划共 {expected} 章，已写 {numbers[-1]} 章）" if expected else ""

    text = "\n\n\n".join(parts).rstrip() + "\n"
    return {
        "filename": filename,
        "title": title,
        "text": text,
        "chapters": len(numbers),
        "firstChapter": numbers[0],
        "lastChapter": numbers[-1],
        "chars": total_chars,
        "missing": missing,
        "empty": empty,
        "gaps": gaps,
        "targetChapters": expected,
        "note": "；".join(x for x in [
            f"缺正文文件：第 {', '.join(map(str, missing))} 章" if missing else "",
            f"空正文：第 {', '.join(map(str, empty))} 章" if empty else "",
            f"章号断档：第 {', '.join(gaps)} 章" if gaps else "",
            tail,
        ] if x),
    }


def export_txt(root: str | os.PathLike) -> dict[str, Any]:
    """写一份到 ``exports/``，返回元信息 + 正文（前端可直接下载同一份内容）。"""
    built = build_export(root)
    path = project_path(root, "exports") / built["filename"]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, built["text"])
    return {
        "ok": True,
        "filename": built["filename"],
        "path": f"exports/{built['filename']}",
        "download": f"/api/projects/export/txt?dir={root}",
        "chapters": built["chapters"],
        "chars": built["chars"],
        "firstChapter": built["firstChapter"],
        "lastChapter": built["lastChapter"],
        "missing": built["missing"],
        "empty": built["empty"],
        "gaps": built["gaps"],
        "note": built["note"],
        "at": datetime.now().isoformat(timespec="seconds"),
    }
