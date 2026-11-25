"""本章参考资料包（RefPack）：写第 N 章时真正装进上下文的那些段落。

规格见 ``design/ux/writing-workbench.md`` §4.8（清单）/ §9.3（数据契约）/ §15.1（技能模块）。

一个 pack 由若干 section 组成，每个 section 是「一段可注入提示词的文本 + UI 要用的元数据」：

- ``key`` / ``group`` / ``label``：清单分组与条目名；
- ``count`` / ``chars`` / ``preview`` / ``truncated``：面板展示与核对「条数 == 实际注入」；
- ``missing`` / ``optional`` / ``source``：缺失时是否标灰、是否允许为空、来源说明；
- ``text``：真正要拼进提示词的内容（默认截断到 1200 字，个别段落另配预算）。

``render_reference_block`` 把 sections 按分组拼成提示词文本；``extra-focus`` 永远最前。
"""

from __future__ import annotations

import os
import re
from typing import Any

from ..store import load_bible, load_project, project_path, read_jsonl
from ..store.jsonl import fold_foreshadow, fold_outline, fold_segments
from . import style as style_mod
from .continuity import (
    character_line,
    continuity_rules_text,
    continuity_trail_text,
    item_line,
    rule_line,
)
from .memory import (
    build_echo_memory,
    character_state,
    effective_relations,
    load_volumes,
    volume_memory,
    volume_of,
)
from .nuewen import REVERSALS as NUWEN_REVERSALS
from .platforms import platform_brief
from .skills import read_skills

OUTLINE_FILE = "ledger/outline.jsonl"
SEGMENTS_FILE = "ledger/segments.jsonl"
FORESHADOW_FILE = "ledger/foreshadow.jsonl"
TIMELINE_FILE = "ledger/timeline.jsonl"

#: 每段注入文本上限；``chars`` 仍记原文长度。
SECTION_LIMIT = 1200
#: 少数段落值得多给预算：人物要多认人，前情要能跨几十章。
SECTION_LIMITS = {
    "characters": 1800,
    "chapter-memory": 4200,
    "relations": 1400,
    "power-system": 900,
    "society": 700,
    "history": 900,
    "glossary": 900,
    "factions": 1000,
    "locations": 1000,
    "items": 1000,
}
#: 面板预览长度。
PREVIEW_LIMIT = 400

#: 分层前情（近 8 章摘要与事件 + 更早一章一句 + 强调回查）的总预算。
ECHO_BUDGET = 6000
#: 时间线最多取最近几条。
TIMELINE_LIMIT = 20

GROUP_ORDER = ("强调", "结构", "伏笔", "人物", "世界", "前情", "写法")


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _num(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _section(
    key: str,
    group: str,
    label: str,
    *,
    text: Any,
    count: int,
    source: str,
    missing: bool = False,
    optional: bool = False,
) -> dict[str, Any]:
    """按该段的预算截断文本，同时保留原始长度与预览。"""
    raw = _text(text)
    limit = int(SECTION_LIMITS.get(key) or SECTION_LIMIT)
    truncated = len(raw) > limit
    body = raw[:limit]
    return {
        "key": key,
        "group": group,
        "label": label,
        "count": int(count or 0),
        "chars": len(raw),
        "preview": raw[:PREVIEW_LIMIT],
        "missing": bool(missing),
        "optional": bool(optional),
        "truncated": truncated,
        "source": source,
        "text": body,
    }


def _count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("- "))


# --------------------------------------------------------------------------- #
# 结构：卷切片 / 段落纲台阶
# --------------------------------------------------------------------------- #


def volume_slice(outline: str, volumes: list[dict[str, Any]], chapter: int) -> tuple[str, dict[str, Any] | None]:
    """本卷大纲切片：卷头到下一个卷头之间；按卷头里的章号区间认，不按卷序猜。"""
    vol = volume_of(volumes, chapter)
    heads = list(re.finditer(r"^\s*###\s*第\s*\d+\s*[卷部].*$", outline, re.M))
    for i, head in enumerate(heads):
        start = head.start()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(outline)
        block = outline[start:end]
        span = re.search(r"第\s*(\d+)\s*[-–—~～至到]\s*(\d+)\s*章", head.group(0))
        if span and int(span.group(1)) <= chapter <= int(span.group(2)):
            return block[:3000], vol or {
                "title": head.group(0).strip("# ").strip(),
                "from": int(span.group(1)),
                "to": int(span.group(2)),
            }
    if vol:
        return outline[:3000], vol
    return outline[:3000], None


def stage_for(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    """本章所在的段落纲台阶。"""
    for seg in fold_segments(read_jsonl(project_path(root, SEGMENTS_FILE))):
        if int(seg.get("from") or 0) <= chapter <= int(seg.get("to") or 0):
            for stage in (seg.get("plan") or {}).get("stages") or []:
                if chapter in [int(x) for x in (stage.get("chapters") or [])]:
                    return stage
    return None


def prev_tail(root: str | os.PathLike, chapter: int, limit: int = 600) -> str:
    """上一章结尾若干字，只作衔接用。"""
    if chapter <= 1:
        return ""
    try:
        from ..store import read_chapter

        text = read_chapter(root, chapter - 1) or ""
    except FileNotFoundError:
        return ""
    return re.sub(r"\s+", " ", text).strip()[-limit:]


def _stage_text(stage: dict[str, Any] | None) -> str:
    if not stage:
        return ""
    fs = stage.get("foreshadow") or {}
    return "\n".join([
        f"目标：{stage.get('goal') or '—'}",
        f"转折：{stage.get('turn') or '—'}",
        f"节奏：{stage.get('pace') or '—'}",
        f"现场：{'、'.join(str(x) for x in (stage.get('places') or [])) or '—'}",
        f"本台阶埋：{'、'.join(fs.get('plant') or []) or '—'}；本台阶收：{'、'.join(fs.get('payoff') or []) or '—'}",
    ])


# --------------------------------------------------------------------------- #
# 伏笔：本章应收/应埋 + 其他未收
# --------------------------------------------------------------------------- #


def _foreshadow_sections(root: str | os.PathLike, chapter: int) -> tuple[str, int, str, int]:
    rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
    open_rows = [r for r in rows if r.get("status") == "open"]
    due = [r for r in open_rows if int(r.get("dueChapter") or 0) == chapter]
    plant = [r for r in open_rows if int(r.get("plantedChapter") or 0) == chapter]
    rest = [r for r in open_rows if r not in due and r not in plant]

    def fmt(f: dict[str, Any], tag: str = "") -> str:
        bits = [f"{f.get('name')}｜第{f.get('plantedChapter')}章埋·计划第{f.get('dueChapter') or '?'}章收"]
        if f.get("plantBeat"):
            bits.append(f"埋点:{f.get('plantBeat')}")
        if f.get("revealChange"):
            bits.append(f"揭开后:{f.get('revealChange')}")
        if f.get("hint"):
            bits.append(f"中途提示:{f.get('hint')}")
        return (f"【{tag}】" if tag else "") + "；".join(bits)

    this = [fmt(f, "本章应收") for f in due] + [fmt(f, "本章应埋") for f in plant]
    other = [fmt(f) for f in rest[:40]]
    return "\n".join(this), len(due) + len(plant), "\n".join(other), len(rest)


# --------------------------------------------------------------------------- #
# 人物 / 世界：从 bible 与记忆层取
# --------------------------------------------------------------------------- #


def _character_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines = [line for line in (character_line(c) for c in (bible.get("characters") or [])[:40]) if line]
    return "\n".join(lines), len(lines)


def _rule_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines = [line for line in (rule_line(r) for r in (bible.get("rules") or [])[:40]) if line]
    return "\n".join(lines), len(lines)


def _world_text(bible: dict[str, Any], project: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    for w in (bible.get("world") or [])[:40]:
        name = _text(w.get("name"))
        if name:
            lines.append(f"【世界·{name}】{_text(w.get('text'))}")
    body = _text(project.get("worldText"))
    if body:
        lines.append("【世界观正文】\n" + body)
    count = len([x for x in (bible.get("world") or []) if _text(x.get("name"))]) + (1 if body else 0)
    return "\n".join(lines), count


def _faction_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    for f in (bible.get("factions") or [])[:40]:
        name = _text(f.get("name"))
        if not name:
            continue
        bits = [b for b in [_text(f.get("text"))] if b]
        if f.get("state"):
            bits.append(f"状态:{f.get('state')}" + (f"（截至第{f.get('stateAt')}章）" if _num(f.get("stateAt")) else ""))
        if f.get("attitude"):
            bits.append(f"对主角:{f.get('attitude')}")
        if f.get("hiddenRules"):
            bits.append(f"暗规:{f.get('hiddenRules')}")
        if f.get("relations"):
            bits.append(f"恩怨:{f.get('relations')}")
        lines.append(f"【势力·{name}】" + "；".join(bits))
    return "\n".join(lines), len(lines)


def _location_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    for x in (bible.get("locations") or [])[:40]:
        name = _text(x.get("name"))
        if not name:
            continue
        bits = [b for b in [_text(x.get("text"))] if b]
        if x.get("state"):
            bits.append(f"状态:{x.get('state')}" + (f"（截至第{x.get('stateAt')}章）" if _num(x.get("stateAt")) else ""))
        if x.get("occupied"):
            bits.append(f"占据:{x.get('occupied')}")
        if x.get("accessRules"):
            bits.append(f"进出:{x.get('accessRules')}")
        lines.append(f"【地点·{name}】" + "；".join(bits))
    return "\n".join(lines), len(lines)


def _item_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines = [line for line in (item_line(x) for x in (bible.get("items") or [])[:40]) if line]
    return "\n".join(lines), len(lines)


def _power_text(bible: dict[str, Any]) -> tuple[str, int]:
    power = bible.get("powerSystem")
    if not isinstance(power, dict):
        return "", 0
    bits = [b for b in (
        f"总名:{_text(power.get('name'))}" if _text(power.get("name")) else "",
        _text(power.get("summary")),
        f"晋升:{_text(power.get('advancement'))}" if _text(power.get("advancement")) else "",
        f"代价:{_text(power.get('costs'))}" if _text(power.get("costs")) else "",
        f"上限:{_text(power.get('limits'))}" if _text(power.get("limits")) else "",
        f"平衡:{_text(power.get('balance'))}" if _text(power.get("balance")) else "",
    ) if b]
    lines = ["- " + "；".join(bits)] if bits else []
    levels = [x for x in (power.get("levels") or []) if isinstance(x, dict) and _text(x.get("name"))]
    if levels:
        lines.append("- 等级台阶：" + " → ".join(
            _text(x.get("name")) + (f"（{_text(x.get('trait'))}）" if _text(x.get("trait")) else "")
            for x in levels[:24]
        ))
    return "\n".join(lines), len(lines)


def _society_text(bible: dict[str, Any]) -> tuple[str, int]:
    society = bible.get("society")
    if not isinstance(society, dict):
        return "", 0
    labels = (
        ("politics", "政治"), ("economy", "经济"), ("currency", "货币"),
        ("law", "律法"), ("taboo", "禁忌"), ("customs", "风俗"),
        ("religion", "宗教"), ("language", "语言"), ("technology", "技术"),
    )
    bits = [f"{label}:{_text(society.get(key))}" for key, label in labels if _text(society.get(key))]
    return ("- " + "；".join(bits), 1) if bits else ("", 0)


def _history_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    for row in (bible.get("history") or [])[:40]:
        if not isinstance(row, dict):
            continue
        event = _text(row.get("event") or row.get("name"))
        if not event:
            continue
        when = "".join(b for b in (_text(row.get("era")), _text(row.get("year"))) if b)
        bits = [f"{event}" + (f"（{when}）" if when else "")]
        if _text(row.get("impact")):
            bits.append(f"影响:{_text(row.get('impact'))}")
        lines.append("- " + "；".join(bits))
    return "\n".join(lines), len(lines)


def _glossary_text(bible: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    for row in (bible.get("glossary") or [])[:80]:
        if not isinstance(row, dict):
            continue
        term = _text(row.get("term") or row.get("name"))
        if not term:
            continue
        bits = [term]
        if _text(row.get("meaning")):
            bits.append(_text(row.get("meaning")))
        if _text(row.get("usage")):
            bits.append(f"用法:{_text(row.get('usage'))}")
        lines.append("- " + "：".join(bits[:2]) + (f"；{bits[2]}" if len(bits) > 2 else ""))
    return "\n".join(lines), len(lines)


def _info_gap_text(bible: dict[str, Any]) -> tuple[str, int]:
    """信息差：谁瞒着什么、谁知道、谁不知道、谁以为自己知道。"""
    lines: list[str] = []
    for g in (bible.get("infoGaps") or [])[:40]:
        if not isinstance(g, dict):
            continue
        secret = _text(g.get("secret"))
        if not secret:
            continue
        bits = [f"秘密:{secret}"]
        for key, label in (("knows", "知道"), ("doesntKnow", "不知道"), ("thinksKnows", "以为知道")):
            if _text(g.get(key)):
                bits.append(f"{label}:{_text(g.get(key))}")
        if _text(g.get("revealChapter")):
            bits.append(f"揭晓:第{g.get('revealChapter')}章")
        lines.append("- " + "；".join(bits))
    return "\n".join(lines), len(lines)


def _relation_text(relations: list[dict[str, Any]], names: list[str]) -> str:
    """底稿 + 已写章节里的关系变化；同一对已按最新章去过重。"""
    rows = []
    for e in relations[:60]:
        a, b = _text(e.get("a")), _text(e.get("b"))
        if not a or not b:
            continue
        if names and a not in names and b not in names:
            continue
        bits = [f"{a} ↔ {b}：{_text(e.get('state')) or '—'}"]
        if _text(e.get("note")):
            bits.append(f"（{_text(e.get('note'))}）")
        rows.append("- " + "".join(bits))
    return "\n".join(rows[:20])


def _names(bible: dict[str, Any]) -> list[str]:
    return [str(c.get("name")) for c in (bible.get("characters") or []) if _text(c.get("name"))]


# --------------------------------------------------------------------------- #
# 前情：章记忆 / 已存档摘要 / 卷记忆 / 时间线 / 上一章结尾
# --------------------------------------------------------------------------- #


def _focus_keys(focus: Any) -> list[str]:
    """把「本章额外强调」变成回查关键词，让更早的相关章不被一句摘要带走。"""
    keys: list[str] = []
    if not isinstance(focus, list):
        return keys
    for item in focus[:8]:
        value = ""
        if isinstance(item, dict):
            value = _text(item.get("key") or item.get("label"))
        else:
            value = _text(item)
        if value and value not in keys:
            keys.append(value)
    return keys


def _chapter_memory_text(root: str | os.PathLike, chapter: int, focus: Any = None) -> tuple[str, int]:
    """分层前情：最近 8 章给摘要/事件/结束状态，再往前 40 章一章一句；命中强调词的远章单独调出。

    这样章节变多时不会只剩最后 8 章——更早的章仍有可读的一句话，并且有预算上限。
    """
    echo = build_echo_memory(
        root, chapter=chapter, budget_chars=ECHO_BUDGET, focus=_focus_keys(focus),
    )
    return str(echo.get("text") or ""), int(echo.get("covered") or 0)


def _timeline_text(root: str | os.PathLike) -> tuple[str, int]:
    rows = [
        r for r in read_jsonl(project_path(root, TIMELINE_FILE))
        if isinstance(r, dict) and not r.get("__corrupt")
    ]
    rows.sort(key=lambda r: (_num(r.get("chapter")), str(r.get("at") or "")))
    picked = rows[-TIMELINE_LIMIT:]
    lines = []
    for r in picked:
        bits = [b for b in [_text(r.get("storyTime")), _text(r.get("place")), _text(r.get("event"))] if b]
        mark = "〔回忆〕" if r.get("flashback") else ""
        lines.append(f"- 第{_num(r.get('chapter'))}章｜{mark}" + "｜".join(bits))
    return "\n".join(lines), len(picked)


# --------------------------------------------------------------------------- #
# 写法：文风 / 平台 / 虐文
# --------------------------------------------------------------------------- #


def _style_text(
    bible: dict[str, Any],
    project: dict[str, Any],
    stage: str,
    *,
    samples: bool = True,
) -> str:
    base, _ = style_mod.resolve_style(bible.get("style"), project.get("platform"), None)
    if not samples:
        base = {**base, "samples": []}
    return style_mod.render_style(base, stage=stage)


# --------------------------------------------------------------------------- #
# focus
# --------------------------------------------------------------------------- #


def _focus_lines(focus: Any) -> list[str]:
    lines: list[str] = []
    if not isinstance(focus, list):
        return lines
    for item in focus[:5]:
        if isinstance(item, dict):
            label = _text(item.get("label") or item.get("key"))
            if not label:
                continue
            kind = _text(item.get("type"))
            key = _text(item.get("key"))
            suffix = f"（{kind}:{key}）" if kind and key else ""
            lines.append(f"- {label}{suffix}")
        elif item:
            lines.append(f"- {_text(item)}")
    return lines


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #


def build_reference_pack(
    root: str | os.PathLike,
    chapter: int,
    *,
    focus: Any = None,
    stage: str = "prose",
    skills: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """组装第 ``chapter`` 章的参考资料包。

    ``stage`` 决定文风维度；``skills`` 是本批实际生效的技能开关——面板和提示词
    必须用同一份，否则「平台打法 / 虐文原则」会在两边一有一无。
    """
    n = int(chapter)
    project = load_project(root) or {}
    bible = load_bible(root)
    effective = read_skills(project)
    if skills:
        unknown = sorted(str(k) for k in skills if k not in effective)
        if unknown:
            raise ValueError(f"未知技能：{'、'.join(unknown)}")
        bad = sorted(str(k) for k, v in skills.items() if not isinstance(v, bool))
        if bad:
            raise ValueError(f"技能开关必须是布尔值：{'、'.join(bad)}")
        effective.update(skills)

    # 结构
    outline_text = _text(project.get("outlineText"))
    volumes = load_volumes(root)
    volume_block, _volume = volume_slice(outline_text, volumes, n) if outline_text else ("", None)
    stage_row = stage_for(root, n)

    # 伏笔
    fs_this, fs_this_count, fs_open, fs_open_count = _foreshadow_sections(root, n)

    # 人物
    chars, char_count = _character_text(bible)
    names = _names(bible)
    state = character_state(root, chapter=n, names=names)["text"] if names else ""
    relations = _relation_text(
        effective_relations(root, bible, before_chapter=n), names,
    )
    gaps, gap_count = _info_gap_text(bible)
    cont_state = continuity_trail_text(bible)

    # 世界
    rules, rule_count = _rule_text(bible)
    world, world_count = _world_text(bible, project)
    factions, faction_count = _faction_text(bible)
    locations, location_count = _location_text(bible)
    items, item_count = _item_text(bible)
    power, power_count = _power_text(bible)
    society, society_count = _society_text(bible)
    history, history_count = _history_text(bible)
    glossary, glossary_count = _glossary_text(bible)

    # 前情：近 8 章详细 + 更早一章一句（已存档摘要折进这一层，不再单独占一段）
    chap_mem, chap_mem_count = _chapter_memory_text(root, n, focus)
    vol_mem = volume_memory(root, chapter=n)["text"]
    timeline, timeline_count = _timeline_text(root)
    tail = prev_tail(root, n)

    # 写法
    style_text = _style_text(bible, project, stage, samples=effective.get("styleSamples", True))
    platform_text = platform_brief(project.get("platform")) if effective.get("platform", True) else ""
    nuewen_on = bool(effective.get("nuewen"))

    focus_lines = _focus_lines(focus)
    title = ""
    for row in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))):
        if _num(row.get("chapter")) == n and _text(row.get("title")):
            title = _text(row.get("title"))
            break

    sections: list[dict[str, Any]] = []
    if focus_lines:
        sections.append(_section(
            "extra-focus", "强调", "本章额外强调",
            text="\n".join(focus_lines), count=len(focus_lines),
            source="本章额外强调",
        ))
    sections += [
        _section("volume-outline", "结构", "本卷大纲",
                 text=volume_block, count=1 if volume_block else 0,
                 source="大纲 + 卷索引", missing=not volume_block),
        _section("stage", "结构", "本章台阶",
                 text=_stage_text(stage_row), count=1 if stage_row else 0,
                 source="段落纲", missing=stage_row is None),
        _section("foreshadow-this", "伏笔", "本章应收/应埋",
                 text=fs_this, count=fs_this_count, source="伏笔账",
                 missing=not fs_this, optional=True),
        _section("foreshadow-open", "伏笔", "其他未收",
                 text=fs_open, count=fs_open_count, source="伏笔账", missing=not fs_open),
        _section("characters", "人物", "人物卡",
                 text=chars, count=char_count, source="bible.characters", missing=not chars),
        _section("character-state", "人物", "人物当前状态",
                 text=state, count=_count_lines(state), source="ledger/memory", missing=not state),
        _section("continuity-state", "人物", "位置轨迹与转手",
                 text=cont_state, count=_count_lines(cont_state), source="bible 人物/物品（写后回写）",
                 missing=not cont_state, optional=True),
        _section("relations", "人物", "人物关系",
                 text=relations, count=_count_lines(relations),
                 source="bible.relations + ledger/relations.json", missing=not relations),
        _section("info-gaps", "人物", "信息差",
                 text=gaps, count=gap_count, source="bible.infoGaps", missing=not gaps, optional=True),
        _section("rules", "世界", "规则",
                 text=rules, count=rule_count, source="bible.rules", missing=not rules),
        _section("world", "世界", "世界观",
                 text=world, count=world_count, source="大纲/世界观", missing=not world),
        _section("factions", "世界", "势力",
                 text=factions, count=faction_count, source="bible.factions", missing=not factions),
        _section("locations", "世界", "地点",
                 text=locations, count=location_count, source="bible.locations", missing=not locations),
        _section("items", "世界", "物品",
                 text=items, count=item_count, source="bible.items", missing=not items),
        _section("power-system", "世界", "力量体系",
                 text=power, count=power_count, source="bible.powerSystem",
                 missing=not power, optional=True),
        _section("society", "世界", "社会常识",
                 text=society, count=society_count, source="bible.society",
                 missing=not society, optional=True),
        _section("history", "世界", "大事记",
                 text=history, count=history_count, source="bible.history",
                 missing=not history, optional=True),
        _section("glossary", "世界", "术语表",
                 text=glossary, count=glossary_count, source="bible.glossary",
                 missing=not glossary, optional=True),
        _section("chapter-memory", "前情", "分层前情（近 8 章摘要 + 更早一章一句）",
                 text=chap_mem, count=chap_mem_count, source="ledger/memory + chapters/index",
                 missing=not chap_mem),
        _section("volume-memory", "前情", "卷摘要",
                 text=vol_mem, count=1 if vol_mem else 0, source="ledger/memory 卷记忆",
                 missing=not vol_mem),
        _section("timeline", "前情", "时间线",
                 text=timeline, count=timeline_count, source="ledger/timeline",
                 missing=not timeline),
        _section("prev-tail", "前情", "上一章结尾",
                 text=tail, count=1 if tail else 0, source="上一章正文",
                 missing=bool(n > 1 and not tail)),
        _section("style", "写法", "文风",
                 text=style_text, count=1 if style_text else 0,
                 source="bible.style / 平台默认", missing=not style_text),
        _section("continuity", "写法", "连贯性",
                 text=continuity_rules_text(), count=4, source="domain.continuity",
                 missing=False, optional=True),
    ]
    # 技能关掉的段直接不入包：面板条数与提示词才真正一致。
    if platform_text:
        sections.append(_section("platform", "写法", "平台打法",
                                 text=platform_text, count=1, source="project.platform"))
    if nuewen_on:
        sections.append(_section("nuewen", "写法", "虐文原则",
                                 text=NUWEN_REVERSALS, count=1, source="project.nuewen"))

    return {
        "chapter": n,
        "title": title or f"第{n}章",
        "sections": sections,
        "summary": {
            "sections": len(sections),
            "items": sum(s["count"] for s in sections),
            "chars": sum(len(s["text"]) for s in sections),
        },
    }


def render_reference_block(pack: dict[str, Any], *, stage: str = "prose") -> str:
    """把 pack 的 sections 按分组拼成提示词文本。

    ``extra-focus`` 永远最前；无内容的段落跳过；被截断的段落明确标注「已按预算截断」。
    """
    del stage  # 预留：不同阶段若需裁掉某些分组，可在此按 stage 过滤
    groups: dict[str, list[dict[str, Any]]] = {}
    for section in pack.get("sections") or []:
        if not _text(section.get("text")):
            continue
        groups.setdefault(str(section.get("group") or "其他"), []).append(section)

    order = list(GROUP_ORDER) + [g for g in groups if g not in GROUP_ORDER]
    parts: list[str] = []
    for group in order:
        rows = groups.get(group) or []
        if not rows:
            continue
        if group != "强调":
            parts.append(f"## {group}")
        for section in rows:
            head = f"【{section.get('label')}】"
            if section.get("truncated"):
                head += f"（已按预算截断，原 {section.get('chars')} 字，以下前 {len(_text(section.get('text')))} 字）"
            parts.append(head + "\n" + _text(section.get("text")))
    return "\n\n".join(parts)


__all__ = [
    "build_reference_pack",
    "render_reference_block",
    "volume_slice",
    "stage_for",
    "prev_tail",
    "SECTION_LIMIT",
    "GROUP_ORDER",
]
