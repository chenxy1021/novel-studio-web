"""Project layout, path resolution, and write-scope guard.

Behaviour mirrors novel-studio/lib/io.js so existing book directories open unchanged.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

LAYOUT = {
    "project": "project.json",
    "bible": "bible.json",
    "map": "map.json",
    "relation_map": "relation_map.json",
    "chapters": "chapters",
    "chapter_index": "chapters/index.json",
    "ledger": "ledger",
    "review": "review",
    "drafts": "drafts",
    "exports": "exports",
}

LEDGER = {
    "bible": "bible.json",
    "foreshadow": "ledger/foreshadow.jsonl",
    "timeline": "ledger/timeline.jsonl",
    "segments": "ledger/segments.jsonl",
    "outline": "ledger/outline.jsonl",
    "review": "ledger/review.jsonl",
    "dismissed": "ledger/dismissed.jsonl",
    "usage": "metrics/usage.jsonl",
    "memory": "ledger/memory.jsonl",
}

# 追加写 + 折叠读的账本；键是 JSONL 里定位当前状态的字段。
LEDGER_KEYS = {
    "foreshadow": "id",
    "timeline": "chapter",
    "segments": ("from", "to"),
    "outline": "chapter",
    "review": None,  # 事件流，不折叠
    "dismissed": "key",
    "usage": None,
    "memory": "chapter",
}

DEFAULT_PROJECTS_DIR = Path(
    os.environ.get("DSH_NOVEL_HOME") or Path.home() / "Desktop" / "mine" / "xiaoshuo"
)

_SYSTEM_ROOTS = {
    "/", "/System", "/Library", "/Applications", "/etc", "/usr",
    "/bin", "/sbin", "/private", "/var",
}
_SYSTEM_PREFIXES = tuple(r + "/" for r in _SYSTEM_ROOTS if r != "/")


def realpath_loose(target: str | os.PathLike) -> Path:
    """Resolve real path; for missing paths resolve the parent instead (mirrors io.js)."""
    abs_ = Path(os.path.abspath(str(target or "")))
    try:
        return abs_.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        parent = abs_.parent
        if parent == abs_:
            return abs_
        return realpath_loose(parent) / abs_.name


def _is_inside(child: Path, parent: Path) -> bool:
    child, parent = Path(os.path.abspath(child)), Path(os.path.abspath(parent))
    return child == parent or str(child).startswith(str(parent) + os.sep)


def _inside_tmp(p: Path) -> bool:
    for root in (tempfile.gettempdir(), "/tmp"):
        if _is_inside(p, root) or _is_inside(p, realpath_loose(root)):
            return True
    return False


def allowed_project_roots(extra: list[str] | None = None) -> list[Path]:
    raw = [
        DEFAULT_PROJECTS_DIR,
        tempfile.gettempdir(),
        "/private" + tempfile.gettempdir(),
        "/tmp",
        *(os.environ.get("DSH_NOVEL_ALLOWED_ROOTS") or "").split(os.pathsep),
        *(extra or []),
    ]
    seen: list[Path] = []
    for x in raw:
        if not x:
            continue
        p = Path(os.path.abspath(str(x)))
        if p not in seen:
            seen.append(p)
    return seen


def assert_writable_root(
    root: str | os.PathLike,
    *,
    creating: bool = False,
    extra_roots: list[str] | None = None,
) -> Path:
    if not os.path.isabs(str(root or "")):
        raise ValueError(f"项目路径必须是绝对路径：{root}")
    abs_ = realpath_loose(root)
    if _inside_tmp(abs_):
        return abs_
    s = str(abs_)
    if s in _SYSTEM_ROOTS or s.startswith(_SYSTEM_PREFIXES):
        raise PermissionError(f"拒绝写入系统目录：{abs_}")
    if abs_ == Path.home().resolve():
        raise PermissionError("拒绝把家目录本身当成小说项目，请建一个子目录")
    if not creating:
        return abs_
    allowed = allowed_project_roots(extra_roots)
    if not any(_is_inside(abs_, base) for base in allowed):
        joined = " 或 ".join(map(str, allowed))
        raise PermissionError(
            f"新项目只能建在 {joined} 之内（要换位置请设 DSH_NOVEL_HOME 或 DSH_NOVEL_ALLOWED_ROOTS）：{abs_}"
        )
    return abs_


def assert_browsable_root(dir: str | os.PathLike) -> Path:
    abs_ = realpath_loose(dir)
    if _inside_tmp(abs_):
        return abs_
    s = str(abs_)
    if s in _SYSTEM_ROOTS or s.startswith(_SYSTEM_PREFIXES):
        raise PermissionError(f"不浏览系统目录：{abs_}")
    return abs_


def safe_join(root: str | os.PathLike, rel: str) -> Path:
    """Resolve a project-relative path (e.g. chapters/001-x.md from index.json) inside root."""
    root_abs = Path(os.path.abspath(root))
    target = Path(os.path.abspath(root_abs / rel))
    if target != root_abs and not str(target).startswith(str(root_abs) + os.sep):
        raise PermissionError(f"路径越出项目目录：{rel}")
    return target


def project_path(root: str | os.PathLike, rel: str) -> Path:
    return Path(os.path.abspath(root)) / rel


def ensure_dir(path: str | os.PathLike) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_files(dir: str | os.PathLike) -> list[str]:
    p = Path(dir)
    if not p.exists():
        return []
    return sorted(n for n in os.listdir(p) if not n.startswith("."))


def is_project(dir: str | os.PathLike) -> bool:
    return (Path(dir) / LAYOUT["project"]).is_file()


def list_project_dirs(base: str | os.PathLike) -> list[Path]:
    base = Path(base)
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".") and is_project(p))


def pad3(n: int | str) -> str:
    return str(n).zfill(3)


def _ascii_slug_words(title: str) -> str:
    out: list[str] = []
    for ch in title:
        if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum():
            out.append(ch)
        elif not out or out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:30] or "未命名"


def chapter_file_path(root: str | os.PathLike, number: int, title: str | None) -> Path:
    """chapters/001-章名.md — 章名只保留中英文数字，最多 30 字（与 io.js 一致）。"""
    return project_path(root, LAYOUT["chapters"]) / f"{pad3(int(number))}-{_ascii_slug_words(str(title or '未命名'))}.md"
