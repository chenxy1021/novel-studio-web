"""chapters/index.json + chapters/*.md.

Keyed by chapter number (1-based). Real books may have gaps, so no array indexing assumptions.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .fsatomic import atomic_write
from .paths import LAYOUT, chapter_file_path, pad3, project_path, safe_join

# 被覆盖前的正文留底：chapters/.versions/001/20261126-101500-123456.md
# 隐藏目录，scan/索引都不看它；每章只留最近 KEEP_VERSIONS 份。
VERSIONS_DIR = ".versions"
KEEP_VERSIONS = 20

_FILE_RE = re.compile(r"^(\d{3,4})-(.*)\.md$")
_COUNT_RE = re.compile(r"[\u4e00-\u9fff]", re.MULTILINE)


def count_chars(text: str) -> int:
    return len(_COUNT_RE.findall(text or ""))


def read_index(root: str | os.PathLike) -> list[dict[str, Any]]:
    p = project_path(root, LAYOUT["chapter_index"])
    if not p.is_file():
        return []
    import json

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"chapters/index.json 解析失败：{e}") from e
    if not isinstance(data, list):
        raise ValueError("chapters/index.json 必须是数组")
    rows = [r for r in data if isinstance(r, dict)]
    for r in rows:
        try:
            r["number"] = int(r.get("number"))
        except (TypeError, ValueError):
            pass
    return sorted(rows, key=lambda r: int(r.get("number") or 0))


def write_index(root: str | os.PathLike, rows: list[dict[str, Any]]) -> Path:
    import json

    ordered = sorted(rows, key=lambda r: int(r.get("number") or 0))
    return atomic_write(project_path(root, LAYOUT["chapter_index"]), json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")


def read_index_entry(root: str | os.PathLike, number: int) -> dict[str, Any] | None:
    n = int(number)
    return next((r for r in read_index(root) if int(r.get("number") or 0) == n), None)


def written_through(root: str | os.PathLike) -> int:
    """已写到第几章：章节索引里的最大章号，没写正文就是 0。

    「写到哪了」只认这一个来源。project.json 里的 currentChapter / gate.chapter
    都是它的派生值，可能因为补存档、回退、手工改文件而落后，不能拿来当真相。
    """
    return max((int(r.get("number") or 0) for r in read_index(root)), default=0)


def next_number(root: str | os.PathLike) -> int:
    """下一章该写的章号 = 已写到的最新章 + 1。"""
    return written_through(root) + 1


def add_to_index(root: str | os.PathLike, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Upsert by number (merge like commitChapter does) and persist. Caller holds the lock."""
    rows = read_index(root)
    n = int(entry["number"])
    for i, row in enumerate(rows):
        if int(row.get("number") or 0) == n:
            rows[i] = {**row, **entry}
            break
    else:
        rows.append(entry)
    write_index(root, rows)
    return rows


def chapter_path(root: str | os.PathLike, entry: dict[str, Any]) -> Path:
    """Resolve entry.file inside root; fall back to the layout path if the field is missing."""
    rel = entry.get("file")
    if rel:
        return safe_join(root, str(rel))
    return chapter_file_path(root, int(entry["number"]), entry.get("title"))


def read_chapter(root: str | os.PathLike, number: int) -> str | None:
    entry = read_index_entry(root, number)
    if not entry:
        return None
    p = chapter_path(root, entry)
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"索引里有第{number}章，但正文文件不在了：{p}") from None


def write_chapter(
    root: str | os.PathLike,
    number: int,
    title: str | None,
    text: str,
) -> tuple[Path, str]:
    """Write body to chapters/NNN-title.md, remove the previous file if the title changed.

    Returns (path, project-relative file). Index update is the caller's job.
    """
    prev = read_index_entry(root, number)
    path = chapter_file_path(root, number, title or (prev or {}).get("title"))
    _save_version(root, number, path, text)
    atomic_write(path, (text or "").strip() + "\n")
    if prev and prev.get("file"):
        old = safe_join(root, str(prev["file"]))
        if old != path:
            try:
                os.unlink(old)
            except FileNotFoundError:
                pass
    rel = str(path.relative_to(Path(os.path.abspath(root))))
    return path, rel


def _save_version(
    root: str | os.PathLike,
    number: int,
    path: Path,
    new_text: str,
) -> None:
    """覆盖正文前把旧文件留一份底；内容没变就不写。

    没有回收站和 undo，手改、AI 重写、重新生成都会盖掉上一版正文——这是最后一道
    可人工找回的保险。版本只写文件，不进索引、不进 SQLite，不参与任何写作逻辑。
    """
    if not path.is_file():
        return
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        return
    if not old.strip() or old == (new_text or "").strip() + "\n":
        return
    d = project_path(root, LAYOUT["chapters"]) / VERSIONS_DIR / pad3(int(number))
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (d / f"{stamp}.md").write_text(old, encoding="utf-8")
    olds = sorted(d.glob("*.md"))
    for extra in olds[:-KEEP_VERSIONS]:
        try:
            extra.unlink()
        except OSError:
            pass


def scan_chapter_files(root: str | os.PathLike) -> list[dict[str, Any]]:
    """List chapters/*.md as {number, fileTitle, file, text} — index rebuild input."""
    d = project_path(root, LAYOUT["chapters"])
    if not d.exists():
        return []
    out = []
    for name in sorted(os.listdir(d)):
        m = _FILE_RE.match(name)
        if not m or name.startswith("."):
            continue
        path = d / name
        out.append({
            "number": int(m.group(1)),
            "fileTitle": m.group(2) or f"第{int(m.group(1))}章",
            "file": f"chapters/{name}",
            "text": path.read_text(encoding="utf-8"),
        })
    return out


def ensure_chapter_dirs(root: str | os.PathLike) -> None:
    for rel in (LAYOUT["chapters"], LAYOUT["ledger"], LAYOUT["review"], LAYOUT["drafts"], LAYOUT["exports"]):
        project_path(root, rel).mkdir(parents=True, exist_ok=True)
