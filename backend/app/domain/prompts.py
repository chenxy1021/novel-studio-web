"""写作提示词库：仓库内置模块 + 书级覆盖，按 ``(path, mtime)`` 缓存。

目录约定：
- 仓库：``<repo>/prompts/<name>.md``
- 书级：``<book>/prompts/<name>.md``，同名时优先于仓库。

只做纯读取，不引入模板引擎；文件内容原样返回。书目录由调用方通过 ``root``
传入（通常是 ``project.json`` 所在目录），未传时只读仓库。
"""

from __future__ import annotations

from pathlib import Path

SUFFIX = ".md"
BOOK_PROMPTS_DIR = "prompts"

#: 仓库根目录下的提示词目录。``prompts.py`` 位于 ``backend/app/domain/``。
REPO_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"

#: 内置模块清单（顺序用于默认装配，不代表加载限制）。
CORE_PROMPTS = (
    "humanize",
    "scene",
    "dialogue",
    "hook",
    "continuity",
    "chapter-quality",
    "style-resolution",
    "review",
    "banned-words",
)

# (绝对路径, mtime 纳秒) -> 文件文本。文件被修改后 mtime 变化，自然换键。
_CACHE: dict[tuple[str, int], str] = {}


class PromptNotFound(ValueError):
    """请求的提示词模块在书级与仓库目录都不存在。"""

    def __init__(self, name: str, searched: list[Path] | None = None) -> None:
        self.name = name
        self.searched = list(searched or [])
        where = "、".join(str(p) for p in self.searched) or "仓库提示词目录"
        super().__init__(f"未找到提示词模块 {name}{SUFFIX}（已查：{where}）")


def normalize_name(name: str) -> str:
    """接受 ``humanize`` 或 ``humanize.md``；拒绝路径分隔符与空名。"""
    stem = str(name or "").strip()
    if stem.endswith(SUFFIX):
        stem = stem[: -len(SUFFIX)]
    if not stem or stem in {".", ".."} or "/" in stem or "\\" in stem or "\x00" in stem:
        raise ValueError(f"非法提示词模块名：{name!r}")
    return stem


def _search_dirs(root: str | Path | None) -> list[Path]:
    dirs: list[Path] = []
    if root is not None:
        dirs.append(Path(root) / BOOK_PROMPTS_DIR)
    dirs.append(REPO_PROMPTS)
    return dirs


def _read_cached(path: Path) -> str:
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        raise
    key = (str(path), mtime)
    text = _CACHE.get(key)
    if text is not None:
        return text
    text = path.read_text(encoding="utf-8")
    _CACHE[key] = text
    return text


def load(name: str, root: str | Path | None = None) -> str:
    """读取模块全文：先书级覆盖，再仓库内置；都找不到抛 ``PromptNotFound``。"""
    stem = normalize_name(name)
    searched: list[Path] = []
    for directory in _search_dirs(root):
        path = directory / f"{stem}{SUFFIX}"
        searched.append(path)
        if not path.is_file():
            continue
        try:
            return _read_cached(path)
        except FileNotFoundError:
            continue
    raise PromptNotFound(stem, searched)


def block(*names: str, root: str | Path | None = None, strict: bool = False) -> str:
    """按传入顺序拼接模块，每块前加 ``## <name>``。

    默认跳过不存在的模块；``strict=True`` 时改为抛 ``PromptNotFound``。
    内容去除首尾空白，块与块之间空一行。
    """
    parts: list[str] = []
    for name in names:
        stem = normalize_name(name)
        try:
            text = load(stem, root=root)
        except PromptNotFound:
            if strict:
                raise
            continue
        parts.append(f"## {stem}\n\n{text.strip()}")
    return "\n\n".join(parts)


def list_prompts(root: str | Path | None = None) -> list[str]:
    """仓库内置与书级覆盖的并集（模块名，不含后缀），按名称排序。"""
    names: set[str] = set()
    for directory in _search_dirs(root):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix == SUFFIX and not path.name.startswith("."):
                names.add(path.stem)
    return sorted(names)


def clear_cache() -> None:
    """清空读取缓存（测试或热更新场景使用）。"""
    _CACHE.clear()
