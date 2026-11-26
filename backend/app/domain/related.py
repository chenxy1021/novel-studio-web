"""相关章节推荐：写这一章之前，哪几章最该回头翻一眼。

不调模型，纯规则打分。理由都是可解释的，作者能判断「这条推荐有没有道理」：

- 同一个人物：候选章出场的人，正是本章细纲里点名的人；
- 同一条伏笔：候选章埋了本章要收的线，或者刚刚收了一条相关的线；
- 同一个地点 / 势力 / 物品：候选章的状态变化还压在本章头上；
- 同卷或相邻卷：结构性关联；
- 距离近：越近的章，越可能还有没交代干净的尾巴。

推荐结果同时进「参考资料包」（``references.py``），写正文时能直接看到。
"""

from __future__ import annotations

import os
from typing import Any

from ..store import project_path, read_index, read_jsonl
from ..store.jsonl import fold_foreshadow, fold_outline
from .memory import load_memory_rows

OUTLINE_FILE = "ledger/outline.jsonl"
FORESHADOW_FILE = "ledger/foreshadow.jsonl"


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _names(value: Any) -> list[str]:
    return [_text(x) for x in (value or []) if _text(x)]


def _entry(root: str | os.PathLike, number: int) -> dict[str, Any] | None:
    return next((r for r in read_index(root) if _num(r.get("number")) == number), None)


def _outline_row(root: str | os.PathLike, number: int) -> dict[str, Any] | None:
    return next((r for r in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE)))
                 if _num(r.get("chapter")) == number), None)


def _volume_at(volumes: list[dict[str, Any]], number: int) -> int:
    for i, v in enumerate(volumes):
        if _num(v.get("from")) <= number <= _num(v.get("to")):
            return i + 1
    return 0


def _brief(row: dict[str, Any] | None) -> str:
    """候选章的「为什么值得回看」一句摘要，优先本章摘要，其次索引摘要。"""
    mem = row or {}
    return _text(mem.get("summary") or mem.get("text"))[:120]


def related_chapters(
    root: str | os.PathLike,
    chapter: int | None = None,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """给出最相关的已写章节，按分数从高到低。

    ``chapter`` 是「即将写 / 正在写」的章号；不传就取当前下一章。候选只包含
    已写进索引的章节，且排除自身。
    """
    index = read_index(root)
    if not index:
        return []
    numbers = [_num(r.get("number")) for r in index if _num(r.get("number")) > 0]
    target = _num(chapter) or (max(numbers) + 1 if numbers else 1)
    memory = load_memory_rows(root)
    by_chapter = memory.get("byChapter") or {}
    volumes = memory.get("volumes") or []
    outline = _outline_row(root, target)
    foreshadows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))

    # 本章要点：细纲里的字段 + 上三章的摘要尾巴（人物/地点会自然延续）。
    beats_text = " ".join([
        _text(outline.get("title")) if outline else "",
        " ".join(_names((outline or {}).get("beats"))),
        " ".join(_names((outline or {}).get("mustInclude"))),
        _text((outline or {}).get("openingState")),
        _text((outline or {}).get("endingState")),
    ])
    prev_tail = " ".join(
        _text((by_chapter.get(n) or {}).get("summary"))
        for n in numbers[-3:] if n <= target
    )
    focus_text = beats_text + " " + prev_tail

    target_cast = set(_names((by_chapter.get(target) or {}).get("characters")))
    for n in numbers[-3:]:
        target_cast.update(_names((by_chapter.get(n) or {}).get("characters")))
    # 当前活着的人物也算「本章相关」：主角即使这一章没被写进细纲，也在场。
    target_cast = {c for c in target_cast if c}

    paid_by_chapter = {
        _num(f.get("payoffChapter")): f
        for f in foreshadows
        if _num(f.get("payoffChapter")) and _text(f.get("status")) == "paid"
    }
    target_volume = _volume_at(volumes, target)

    out: list[dict[str, Any]] = []
    for row in index:
        n = _num(row.get("number"))
        if n <= 0 or n == target:
            continue
        mem = by_chapter.get(n) or {}
        score = 0.0
        reasons: list[str] = []

        cast = set(_names(mem.get("characters")))
        shared = sorted(target_cast & cast)
        if shared:
            score += min(6.0, 2.0 * len(shared))
            reasons.append("出场人物重合：" + "、".join(shared[:4]))

        # 伏笔：候选章埋的线还没收，且本章准备碰它；或候选章刚收了一条本章相关的线。
        for f in foreshadows:
            p = _num(f.get("plantedChapter"))
            q = _num(f.get("payoffChapter"))
            if p != n:
                continue
            status = _text(f.get("status")) or "open"
            if status == "open":
                score += 1.0
                reasons.append(f"埋了未收的伏笔「{_text(f.get('name'))[:16]}」")
            elif q == target:
                score += 3.0
                reasons.append(f"这条伏笔计划在本章收：{_text(f.get('name'))[:16]}")
        if n in paid_by_chapter:
            f = paid_by_chapter[n]
            key = _text(f.get("name"))
            if key and key in focus_text:
                score += 1.5
                reasons.append(f"刚收的伏笔和本章相关：{key[:16]}")

        # 地点 / 势力 / 物品状态：本章细纲里点到、候选章里有过变化。
        for field, label in (("places", "地点"), ("placeStates", "地点状态"),
                             ("factionStates", "势力状态"), ("items", "物品")):
            values: list[str] = []
            for item in (mem.get(field) or []):
                if isinstance(item, dict):
                    values.extend(_names([item.get("name"), item.get("who"), item.get("to")]))
                else:
                    values.extend(_names([item]))
            hit = [v for v in values if v and v in focus_text]
            if hit:
                score += 1.2 * len(hit)
                reasons.append(f"{label}仍在延续：" + "、".join(dict.fromkeys(hit))[:30])

        # 卷与距离：越近越值得回看。
        vol = _volume_at(volumes, n)
        if target_volume and vol == target_volume:
            score += 1.5
            reasons.append("同一卷")
        elif target_volume and abs(vol - target_volume) == 1 and vol:
            score += 0.5
        gap = target - n
        if gap <= 2:
            score += 5.0
            reasons.append("紧挨着的上一章")
        elif gap <= 5:
            score += 2.5
        elif gap <= 10:
            score += 1.0

        if score <= 0:
            continue
        out.append({
            "number": n,
            "title": _text(row.get("title")) or f"第{n}章",
            "volume": vol,
            "chars": _num(row.get("chars")),
            "verdict": _text(row.get("verdict")),
            "summary": _brief(mem) or _text(row.get("summary"))[:120],
            "score": round(score, 1),
            "reasons": reasons[:4],
        })

    out.sort(key=lambda r: (-r["score"], -r["number"]))
    return out[:max(1, min(20, int(limit or 8)))]


def related_block(root: str | os.PathLike, chapter: int | None = None, limit: int = 5) -> str:
    """给参考资料包用的 Markdown 片段；没有推荐就返回空串。"""
    rows = related_chapters(root, chapter, limit=limit)
    if not rows:
        return ""
    lines = ["写这章之前值得回看的章节："]
    for r in rows:
        why = "；".join(r["reasons"][:3])
        bits = [f"第{r['number']}章《{r['title']}》"]
        if why:
            bits.append(why)
        if r.get("summary"):
            bits.append(r["summary"][:80])
        lines.append("- " + "——".join(bits))
    return "\n".join(lines)
