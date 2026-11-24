"""提示词加载器：仓库内置、书级覆盖、strict、列表与缓存。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain import prompts as prompt_loader
from app.domain.prompts import PromptNotFound

CORE = prompt_loader.CORE_PROMPTS
REQUIRED_SECTIONS = ("## 用途", "## 硬规则", "## 检查清单", "## 反模式", "## 输出约束")


def make_book(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    root = tmp_path / "书"
    root.mkdir()
    if files:
        prompts_dir = root / "prompts"
        prompts_dir.mkdir()
        for name, text in files.items():
            (prompts_dir / f"{name}.md").write_text(text, encoding="utf-8")
    return root


def test_repo_has_all_nine_modules() -> None:
    assert len(CORE) == 9
    for name in CORE:
        text = prompt_loader.load(name)
        assert text.strip(), f"{name} 为空"
        assert text.lstrip().startswith("# "), f"{name} 缺少标题"
        for section in REQUIRED_SECTIONS:
            assert section in text, f"{name} 缺少 {section}"


def test_list_prompts_includes_repo_modules() -> None:
    names = prompt_loader.list_prompts()
    assert set(CORE) <= set(names)
    assert names == sorted(names)
    # 仓库里的既有模块也应在并集里，不会被内置清单过滤
    assert "虐文" in names


def test_book_override_wins_and_dot_md_alias(tmp_path: Path) -> None:
    override = "# 书级人味\n\n## 用途\n\n这本书自己的版本。\n"
    root = make_book(tmp_path, {"humanize": override})
    assert prompt_loader.load("humanize", root=root) == override
    assert prompt_loader.load("humanize.md", root=root) == override


def test_book_falls_back_to_repo(tmp_path: Path) -> None:
    root = make_book(tmp_path, {"humanize": "# 书级\n\n只覆盖一个模块。\n"})
    assert prompt_loader.load("scene", root=root) == prompt_loader.load("scene")
    assert prompt_loader.list_prompts(root=root) == sorted(
        set(CORE) | {"虐文"}
    )


def test_block_order_and_headings(tmp_path: Path) -> None:
    root = make_book(tmp_path, {
        "review": "# 审稿\n\n书级 A。\n",
        "hook": "# 钩子\n\n书级 B。\n",
    })
    out = prompt_loader.block("review", "hook", root=root)
    assert out.startswith("## review\n\n# 审稿")
    assert out.index("## review") < out.index("## hook")
    assert out.endswith("书级 B。")


def test_missing_module_skipped_by_default(tmp_path: Path) -> None:
    root = make_book(tmp_path)
    out = prompt_loader.block("humanize", "no-such-module", root=root)
    assert out.startswith("## humanize")
    assert "## no-such-module" not in out


def test_missing_module_raises_in_strict_mode(tmp_path: Path) -> None:
    root = make_book(tmp_path)
    with pytest.raises(PromptNotFound) as excinfo:
        prompt_loader.block("humanize", "no-such-module", root=root, strict=True)
    assert excinfo.value.name == "no-such-module"
    assert isinstance(excinfo.value, ValueError)
    assert any("no-such-module" in str(p) for p in excinfo.value.searched)


def test_missing_load_raises_prompt_not_found(tmp_path: Path) -> None:
    root = make_book(tmp_path)
    with pytest.raises(PromptNotFound):
        prompt_loader.load("no-such-module", root=root)


def test_list_prompts_union_and_hidden_ignored(tmp_path: Path) -> None:
    root = make_book(tmp_path, {"humanize": "# 覆盖\n", "custom-note": "# 额外\n"})
    prompts_dir = root / "prompts"
    (prompts_dir / ".hidden.md").write_text("# 隐藏\n", encoding="utf-8")
    names = prompt_loader.list_prompts(root=root)
    assert set(CORE) <= set(names)
    assert {"humanize", "custom-note"} <= set(names)
    assert ".hidden" not in names
    assert "custom-note" not in prompt_loader.list_prompts()


def test_cache_hit_avoids_second_read(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt_loader.clear_cache()
    first = prompt_loader.load("scene")

    calls: list[Path] = []
    original = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs):
        calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    second = prompt_loader.load("scene")
    assert second is first
    assert calls == []


def test_cache_refreshes_after_file_change(tmp_path: Path) -> None:
    prompt_loader.clear_cache()
    root = make_book(tmp_path, {"humanize": "# 第一版\n"})
    assert prompt_loader.load("humanize", root=root) == "# 第一版\n"
    (root / "prompts" / "humanize.md").write_text("# 第二版\n", encoding="utf-8")
    assert prompt_loader.load("humanize", root=root) == "# 第二版\n"


def test_invalid_names_rejected() -> None:
    for bad in ("", "   ", "../humanize", "a/b", "a\\b", ".md"):
        with pytest.raises(ValueError):
            prompt_loader.load(bad)
