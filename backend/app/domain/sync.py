"""手改回灌：作者在应用外改了 ``chapters/*.md``，把派生数据重新对齐。

正文是唯一真相，索引和记忆都是它的派生值。应用内外都能写正文，但只有应用内
写的时候才会顺手更新索引、章记忆、人物状态。手改之后，这些派生值会停在旧稿上：

- ``chapters/index.json`` 的字数 / 判定 / 摘要还是旧的；
- ``ledger/memory.jsonl`` 的章记忆描述的是改前的剧情；
- bible 里的人物位置、物品持有人、势力状态还是按旧稿并进去的。

这里按「正文指纹」找出被改过的章，逐章重走一遍应用内写正文后的回灌：

1. 记下新正文的指纹（索引 + 章记忆各一份）；
2. ``undo_chapter`` 把这一章并进 bible 的连续性变化撤掉；
3. 重新生成章记忆（这一步要调模型）；
4. ``reapply_chapter`` 按新记忆并回 bible；
5. 重算索引里的字数 / 判定 / 章末钩子。

只处理「正文变了」的章。旧书索引里没有指纹的，第一次只补基线，不重跑记忆。
"""

from __future__ import annotations

import os
from typing import Any, Callable

from ..store import add_to_index, project_path, read_index, read_jsonl
from ..store.chapter import scan_chapter_files
from ..store.chapter import text_hash as chapter_text_hash
from .continuity import reapply_chapter, undo_chapter
from .memory_gen import generate_chapter_memory
from .review import _entry_from_text, close_ai_round

MEMORY_FILE = "ledger/memory.jsonl"


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _memory_by_chapter(root: str | os.PathLike) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in read_jsonl(project_path(root, MEMORY_FILE)):
        if not isinstance(row, dict) or row.get("__corrupt"):
            continue
        if row.get("kind") in ("volume", "character-state") or row.get("chapter") is None:
            continue
        n = _num(row.get("chapter"))
        if n > 0:
            out[n] = row
    return out


def scan_sync(root: str | os.PathLike) -> dict[str, Any]:
    """找出「正文和应用内记录对不上」的章，以及没有进索引的文件。

    ``kind``：
    - ``edited``：索引里有指纹，和当前文件不一致——正文被应用外改过；
    - ``untracked``：目录里有正文文件，索引里没有；
    - ``baseline``：旧书索引里没指纹，第一次只能补基线；
    - ``missing``：索引里有这一章，文件不在了（可能是手滑删掉）；
    - ``memory-stale``：正文没变，但章记忆的指纹对不上（上次回灌中途失败）。
    """
    index = {_num(e.get("number")): e for e in read_index(root) if _num(e.get("number")) > 0}
    files = {_num(f.get("number")): f for f in scan_chapter_files(root)}
    memory = _memory_by_chapter(root)

    items: list[dict[str, Any]] = []
    for n in sorted(set(index) | set(files)):
        entry = index.get(n) or {}
        file = files.get(n) or {}
        text = str(file.get("text") or "")
        title = _text(file.get("fileTitle")) or _text(entry.get("title")) or f"第{n}章"
        base: dict[str, Any] = {
            "number": n,
            "title": title,
            "chars": len(text),
            "indexed": n in index,
            "hasFile": n in files,
        }
        if n in files and n not in index:
            items.append({**base, "kind": "untracked",
                          "reason": "目录里有正文，索引里没有（可能是复制进来的稿子）"})
            continue
        if n in index and n not in files:
            items.append({**base, "kind": "missing",
                          "reason": "索引里有这一章，正文文件不在了"})
            continue
        current = chapter_text_hash(text)
        recorded = _text(entry.get("sha256"))
        if not recorded:
            items.append({**base, "kind": "baseline", "sha256": current,
                          "reason": "旧索引没有正文指纹，第一次只补基线，不重跑记忆"})
            continue
        mem = memory.get(n) or {}
        mem_hash = _text(mem.get("sha256"))
        stale_memory = bool(mem.get("summary")) and bool(mem_hash) and mem_hash != current
        if recorded != current:
            items.append({**base, "kind": "edited", "sha256": current,
                          "recorded": recorded, "memoryStale": stale_memory,
                          "reason": "正文在应用外被改过，索引和记忆还是旧稿"})
        elif stale_memory:
            # 只在「记忆自带指纹且对不上」时标过期。老记忆没有指纹就无从判断，
            # 不能把整本旧书的记忆都当成过期、哄作者全部重跑一遍。
            items.append({**base, "kind": "memory-stale", "sha256": current,
                          "recorded": recorded,
                          "reason": "正文没变，但章记忆不是照当前正文提炼的"})

    return {
        "items": items,
        "counts": {
            "edited": sum(1 for x in items if x["kind"] == "edited"),
            "untracked": sum(1 for x in items if x["kind"] == "untracked"),
            "baseline": sum(1 for x in items if x["kind"] == "baseline"),
            "missing": sum(1 for x in items if x["kind"] == "missing"),
            "memoryStale": sum(1 for x in items if x["kind"] == "memory-stale"),
        },
        "chapters": len(files),
        "indexed": len(index),
    }


def apply_sync(
    root: str | os.PathLike,
    numbers: list[int] | None = None,
    *,
    regenerate_memory: bool = True,
    model: str | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把选中的章回灌一遍；不传 ``numbers`` 就处理所有非 ``missing`` 的差异。"""
    scan = scan_sync(root)
    wanted = {int(n) for n in (numbers or []) if _num(n) > 0}
    targets = [
        x for x in scan["items"]
        if x["kind"] != "missing" and (not wanted or x["number"] in wanted)
    ]
    files = {_num(f.get("number")): f for f in scan_chapter_files(root)}

    results: list[dict[str, Any]] = []
    for item in sorted(targets, key=lambda x: x["number"]):
        n = item["number"]
        out: dict[str, Any] = {"number": n, "title": item["title"], "kind": item["kind"],
                               "ok": False, "steps": []}
        text = str((files.get(n) or {}).get("text") or "")
        if not text.strip():
            out["error"] = "正文为空，跳过"
            results.append(out)
            continue
        if on_stage:
            on_stage(f"回灌第 {n} 章")

        entry = next((e for e in read_index(root) if _num(e.get("number")) == n), {})
        if item["kind"] == "untracked" or not entry:
            entry = {
                "number": n,
                "title": item["title"],
                "file": str((files.get(n) or {}).get("file") or f"chapters/{n:03d}-{item['title']}.md"),
            }
            add_to_index(root, _entry_from_text(entry, text))
            out["steps"].append("added-to-index")

        # 旧索引没指纹：只补基线、重算索引字段，不重跑记忆（否则整本旧书都要重烧一遍）。
        if not regenerate_memory or item["kind"] == "baseline":
            changed = _write_index_entry(root, n, text, entry)
            out.update(ok=True, **changed)
            out["steps"].append("baseline" if item["kind"] == "baseline" else "index-only")
            results.append(out)
            continue

        try:
            undo_chapter(root, n)
            out["steps"].append("undo")
            generate_chapter_memory(root, n, model=model, force=True)
            out["steps"].append("memory")
            reapply_chapter(root, n)
            out["steps"].append("reapply")
        except Exception as e:  # noqa: BLE001 — 单章失败不挡其他章，作者能看到是哪章
            out["error"] = f"{type(e).__name__}: {e}"
            out["memoryStale"] = True
            # 记忆没换成，就别把索引指纹改成新值，否则下次扫描会以为已经对齐。
            results.append(out)
            continue

        changed = _write_index_entry(root, n, text, entry)
        out.update(ok=True, **changed)
        results.append(out)

    ok = [r for r in results if r.get("ok")]
    return {
        "ok": bool(ok) or not results,
        "results": results,
        "applied": [r["number"] for r in ok],
        "failed": [r for r in results if not r.get("ok")],
        "skipped": [x["number"] for x in scan["items"] if x["kind"] == "missing"],
        "memoryRegenerated": bool(regenerate_memory),
    }


def _write_index_entry(root: str | os.PathLike, n: int, text: str, entry: dict[str, Any]) -> dict[str, Any]:
    """用当前正文重算索引字段，保留作者已确认 / 复检轮次这些人工状态。"""
    fresh = _entry_from_text({
        **{k: v for k, v in entry.items() if k not in ("chars", "verdict", "chapterVerdict",
                                                       "aiTellDensity", "dialogueRatio",
                                                       "endHook", "fixReasons", "summary")},
        "number": n,
        "title": entry.get("title") or f"第{n}章",
    }, text)
    add_to_index(root, fresh)
    close_ai_round(root, n, "edit")
    return {"chars": fresh.get("chars"), "verdict": fresh.get("verdict")}
