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
    character_status_at,
    continuity_rules_text,
    continuity_trail_text,
    item_line,
    normalize_status,
    rule_line,
)
from .memory import (
    build_echo_memory,
    character_state,
    effective_relations,
    load_memory_rows,
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
    # 「谁在第几章知道了什么」是最容易写后忘前的一层，多给一点预算。
    "character-state": 1800,
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
#: 必须与 ``SECTION_LIMITS["chapter-memory"]`` 一致：前情自己按预算优雅地丢远章，
#: 若段预算更小，section 会在它收口之后再从尾巴硬切，把最近几章也切掉。
ECHO_BUDGET = SECTION_LIMITS["chapter-memory"]
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
    kept: int | None = None,
) -> dict[str, Any]:
    """按该段的预算收口文本，同时保留原始长度与预览。

    ``kept`` 是真正展开的条数（清单型段落由 ``_pack`` 给出）；少于 ``count``
    就标「截断」，面板据此显示「4/9 条」，不假装整段都进了提示词。
    """
    raw = _text(text)
    limit = int(SECTION_LIMITS.get(key) or SECTION_LIMIT)
    body = _trim_to_limit(raw, limit)
    dropped = kept is not None and int(kept) < int(count or 0)
    return {
        "key": key,
        "group": group,
        "label": label,
        "count": int(count or 0),
        "kept": int(kept) if kept is not None else int(count or 0),
        "chars": len(raw),
        "preview": raw[:PREVIEW_LIMIT],
        "missing": bool(missing),
        "optional": bool(optional),
        "truncated": len(raw) > limit or dropped,
        "source": source,
        "text": body,
    }


def _count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("- "))


def _trim_to_limit(raw: str, limit: int) -> str:
    """超预算时的兜底收口：先按整行，再按整句，最后才硬切。

    原来的 ``raw[:limit]`` 会从半句话、甚至半个人名处断开——提示词里出现
    「【人物·赵」这种残行，模型只能当它不存在，正是「写后忘前」的来源。
    """
    if len(raw) <= limit:
        return raw
    rows: list[str] = []
    used = 0
    for line in raw.splitlines():
        if used + len(line) + 1 > limit:
            break
        rows.append(line)
        used += len(line) + 1
    if rows and len("\n".join(rows)) > limit * 0.6:
        return "\n".join(rows)
    head = raw[:limit]
    cut = max(head.rfind(mark) for mark in ("。", "！", "？", "；", "\n"))
    if cut >= limit // 2:
        return head[: cut + 1]
    return head


# --------------------------------------------------------------------------- #
# 按相关度装包：整条进、整条出，装不下的折成一报名录
# --------------------------------------------------------------------------- #

#: 判「最近出场」时回看几章。
RECENT_CAST_SPAN = 3
#: 已离场的人物排在最后：没被本章上下文点名，就不抢人物卡的预算。
_GONE_STATUS = {"dead", "missing", "exited"}


def _hot(focus_text: str, names: Any) -> bool:
    """这些名字（含别名）有没有出现在本章相关上下文里（台阶/细纲/上一章结尾/强调）。"""
    if not focus_text:
        return False
    for name in names or ():
        value = _text(name)
        if len(value) >= 2 and value in focus_text:
            return True
    return False


def _character_names(character: dict[str, Any]) -> list[str]:
    names = [_text(character.get("name"))]
    aliases = character.get("aliases")
    if isinstance(aliases, list):
        names.extend(_text(a) for a in aliases)
    return [n for n in names if n]


def _records(text: str) -> list[str]:
    """把清单文本切成记录：顶格行起新记录，缩进行并进上一条（人物状态是多行一块）。"""
    out: list[list[str]] = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        if line[:1] in (" ", "\t") and out:
            out[-1].append(line)
        else:
            out.append([line])
    return ["\n".join(rows) for rows in out]


def _brief(record: str, *, status: bool = False) -> str:
    """名录用的短名：【地点·旧码头】→ 旧码头；人物再带一眼状态。"""
    first = record.splitlines()[0].strip()
    name = ""
    m = re.match(r"^【(?:[^·】]+·)?([^】]+)】", first)
    if m:
        name = m.group(1).strip()
    else:
        plain = re.sub(r"^[-*•\s]+", "", first)
        name = re.split(r"[｜；：]", plain)[0].strip()
        name = re.sub(r"^\[[^\]]+\]\s*", "", name).strip()
    name = name[:16]
    if status and name:
        st = re.search(r"状态:([^；]+)", first)
        if st:
            label = re.sub(r"（第\d+章起）", "", st.group(1)).strip()
            if label and label not in ("在场", "active"):
                return f"{name}({label})"
    return name


def _pack(records: list[str], limit: int, briefs: list[str] | None = None,
          *, status_briefs: bool = False) -> tuple[str, int]:
    """把已按相关度排好序的记录整条装进预算，返回 (文本, 真正展开的条数)。

    装不下的记录压成最后一行「（其余 N 条未展开：名字、名字…）」——名字和状态
    至少还在，模型不会把没展开的人物当成不存在。绝不从半句处切开。
    """
    rows = [r for r in records if _text(r)]
    if not rows:
        return "", 0
    shorts = [_text(b) or _brief(r, status=status_briefs) for b, r in zip(list(briefs or []), rows)]
    shorts += [""] * (len(rows) - len(shorts))
    kept: list[str] = []
    used = 0
    for i, row in enumerate(rows):
        rest = rows[i + 1:]
        tail = _roster(len(rest), shorts[i + 1:]) if rest else ""
        cost = len(row) + (1 if kept else 0) + (len(tail) + 1 if tail else 0)
        if kept and used + cost > limit:
            break
        kept.append(row)
        used += len(row) + 1
    body = "\n".join(kept)
    rest_count = len(rows) - len(kept)
    if rest_count:
        tail = _roster(rest_count, shorts[len(kept):])
        room = limit - len(body) - (1 if body else 0)
        if room > 8:
            if len(tail) > room:
                tail = tail[: room - 1].rstrip("、，") + "…"
            body = body + "\n" + tail if body else tail
    if len(body) > limit:
        body = body[: max(0, limit - 1)] + "…"
    return body, len(kept)


def _roster(count: int, shorts: list[str]) -> str:
    names = "、".join(s for s in shorts if s)
    return f"- （其余 {count} 条未展开：{names}）" if names else f"- （其余 {count} 条未展开）"


def _rank_names(names: list[str], focus_text: str, recent: set[str]) -> list[str]:
    """人物状态表的顺序：本章上下文点名的在前，最近出场的其次。"""
    def rank(item: tuple[int, str]) -> tuple[int, int]:
        index, name = item
        if _hot(focus_text, [name]):
            return (0, index)
        if name in recent:
            return (1, index)
        return (2, index)
    return [name for _, name in sorted(enumerate(names), key=rank)]


def _recent_cast(root: str | os.PathLike, chapter: int) -> set[str]:
    """最近几章出场过的人：没被本章点名，也比全书路人更该留在提示词里。"""
    try:
        by_chapter = load_memory_rows(root)["byChapter"]
    except Exception:  # noqa: BLE001 - 记忆层坏掉不该拖垮参考资料
        return set()
    names: set[str] = set()
    for ch in range(max(1, chapter - RECENT_CAST_SPAN), chapter):
        row = by_chapter.get(ch) or {}
        names.update(str(x) for x in (row.get("characters") or []) if x)
    return names


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


def _foreshadow_sections(root: str | os.PathLike, chapter: int) -> tuple[str, int, str, int, int]:
    """返回 (本章应收应埋, 其条数, 其他未收, 未收总条数, 未收真正展开条数)。

    其他未收按「计划收的章」从近到远排：快到期的最该在写的时候被想起来，
    而不是按账本录入顺序取前 40 条。
    """
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

    rest = sorted(rest, key=lambda r: (
        _num(r.get("dueChapter")) or 10**6,
        -_num(r.get("plantedChapter")),
        _text(r.get("name")),
    ))
    this = [fmt(f, "本章应收") for f in due] + [fmt(f, "本章应埋") for f in plant]
    limit = int(SECTION_LIMITS.get("foreshadow-open") or SECTION_LIMIT)
    other, kept = _pack(
        [fmt(f) for f in rest],
        limit,
        [_text(f.get("name")) for f in rest],
    )
    return "\n".join(this), len(due) + len(plant), other, len(rest), kept


# --------------------------------------------------------------------------- #
# 人物 / 世界：从 bible 与记忆层取
# --------------------------------------------------------------------------- #


def _character_text(bible: dict[str, Any], *, focus_text: str = "", recent: set[str] | None = None) -> tuple[str, int, int]:
    """人物卡按相关度装包：本章点名的 → 最近出场的 → 其他活人 → 已离场。"""
    recent = recent or set()
    ranked: list[tuple[int, int, str, str]] = []
    for i, c in enumerate((bible.get("characters") or [])[:40]):
        if not isinstance(c, dict):
            continue
        line = character_line(c)
        if not line:
            continue
        if _hot(focus_text, _character_names(c)):
            rank = 0
        elif _text(c.get("name")) in recent:
            rank = 1
        elif normalize_status(character_status_at(c)["current"]) in _GONE_STATUS:
            rank = 3
        else:
            rank = 2
        ranked.append((rank, i, line, _brief(line, status=True)))
    ranked.sort(key=lambda r: (r[0], r[1]))
    limit = int(SECTION_LIMITS.get("characters") or SECTION_LIMIT)
    body, kept = _pack([r[2] for r in ranked], limit, [r[3] for r in ranked])
    return body, len(ranked), kept


def _rule_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int, int]:
    rows: list[tuple[int, int, str]] = []
    for i, r in enumerate((bible.get("rules") or [])[:40]):
        line = rule_line(r)
        if not line:
            continue
        rows.append((0 if _hot(focus_text, [_text(r.get("name")), _text(r.get("text"))]) else 1, i, line))
    rows.sort(key=lambda r: (r[0], r[1]))
    limit = int(SECTION_LIMITS.get("rules") or SECTION_LIMIT)
    body, kept = _pack([r[2] for r in rows], limit)
    return body, len(rows), kept


def _world_text(bible: dict[str, Any], project: dict[str, Any], *, focus_text: str = "") -> tuple[str, int]:
    """世界观条目按相关度排，正文放最后——正文是整块散文，由 _section 按整句收口。"""
    rows: list[tuple[int, int, str]] = []
    for i, w in enumerate((bible.get("world") or [])[:40]):
        name = _text(w.get("name"))
        if name:
            rows.append((0 if _hot(focus_text, [name]) else 1, i, f"【世界·{name}】{_text(w.get('text'))}"))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [r[2] for r in rows]
    body = _text(project.get("worldText"))
    if body:
        lines.append("【世界观正文】\n" + body)
    count = len(rows) + (1 if body else 0)
    return "\n".join(lines), count


def _faction_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int, int]:
    rows: list[tuple[int, int, int, str]] = []
    for i, f in enumerate((bible.get("factions") or [])[:40]):
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
        hot = _hot(focus_text, [name])
        rows.append((0 if hot else 1, -_num(f.get("stateAt")), i, f"【势力·{name}】" + "；".join(bits)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    limit = int(SECTION_LIMITS.get("factions") or SECTION_LIMIT)
    body, kept = _pack([r[3] for r in rows], limit)
    return body, len(rows), kept


def _location_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int, int]:
    rows: list[tuple[int, int, int, str]] = []
    for i, x in enumerate((bible.get("locations") or [])[:40]):
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
        hot = _hot(focus_text, [name])
        rows.append((0 if hot else 1, -_num(x.get("stateAt")), i, f"【地点·{name}】" + "；".join(bits)))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    limit = int(SECTION_LIMITS.get("locations") or SECTION_LIMIT)
    body, kept = _pack([r[3] for r in rows], limit)
    return body, len(rows), kept


def _item_text(bible: dict[str, Any], *, focus_text: str = "", recent: set[str] | None = None) -> tuple[str, int, int]:
    """物品卡：本章点名的 → 最近出手过/最近出现状态变化的 → 其他。"""
    recent = recent or set()
    rows: list[tuple[int, int, int, str]] = []
    for i, x in enumerate((bible.get("items") or [])[:40]):
        line = item_line(x)
        if not line:
            continue
        name = _text(x.get("name"))
        if _hot(focus_text, [name]):
            rank = 0
        elif _text(x.get("holder")) in recent:
            rank = 1
        else:
            rank = 2
        rows.append((rank, -_num(x.get("stateAt")), i, line))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    limit = int(SECTION_LIMITS.get("items") or SECTION_LIMIT)
    body, kept = _pack([r[3] for r in rows], limit)
    return body, len(rows), kept


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


def _history_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int, int]:
    rows: list[tuple[int, int, str]] = []
    for i, row in enumerate((bible.get("history") or [])[:40]):
        if not isinstance(row, dict):
            continue
        event = _text(row.get("event") or row.get("name"))
        if not event:
            continue
        when = "".join(b for b in (_text(row.get("era")), _text(row.get("year"))) if b)
        bits = [f"{event}" + (f"（{when}）" if when else "")]
        if _text(row.get("impact")):
            bits.append(f"影响:{_text(row.get('impact'))}")
        hot = _hot(focus_text, [event, _text(row.get("impact"))])
        rows.append((0 if hot else 1, i, "- " + "；".join(bits)))
    rows.sort(key=lambda r: (r[0], r[1]))
    limit = int(SECTION_LIMITS.get("history") or SECTION_LIMIT)
    body, kept = _pack([r[2] for r in rows], limit)
    return body, len(rows), kept


def _glossary_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int, int]:
    """术语表最容易被从中间腰斩：32 条只装得下一半，必须优先留本章用得到的词。"""
    rows: list[tuple[int, int, str, str]] = []
    for i, row in enumerate((bible.get("glossary") or [])[:80]):
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
        line = "- " + "：".join(bits[:2]) + (f"；{bits[2]}" if len(bits) > 2 else "")
        rows.append((0 if _hot(focus_text, [term]) else 1, i, line, term))
    rows.sort(key=lambda r: (r[0], r[1]))
    limit = int(SECTION_LIMITS.get("glossary") or SECTION_LIMIT)
    body, kept = _pack([r[2] for r in rows], limit, [r[3] for r in rows])
    return body, len(rows), kept


def _info_gap_text(bible: dict[str, Any], *, focus_text: str = "") -> tuple[str, int]:
    """信息差：谁瞒着什么、谁知道、谁不知道、谁以为自己知道。"""
    rows: list[tuple[int, int, str]] = []
    for i, g in enumerate((bible.get("infoGaps") or [])[:40]):
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
        hot = any(_hot(focus_text, [_text(g.get(k))]) for k in ("knows", "doesntKnow", "thinksKnows"))
        rows.append((0 if hot else 1, i, "- " + "；".join(bits)))
    rows.sort(key=lambda r: (r[0], r[1]))
    return "\n".join(r[2] for r in rows), len(rows)


def _relation_text(relations: list[dict[str, Any]], names: list[str], *, focus_text: str = "") -> str:
    """底稿 + 已写章节里的关系变化；同一对已按最新章去过重。"""
    rows: list[tuple[int, int, str]] = []
    for i, e in enumerate(relations[:60]):
        a, b = _text(e.get("a")), _text(e.get("b"))
        if not a or not b:
            continue
        if names and a not in names and b not in names:
            continue
        bits = [f"{a} ↔ {b}：{_text(e.get('state')) or '—'}"]
        if _text(e.get("note")):
            bits.append(f"（{_text(e.get('note'))}）")
        hot = _hot(focus_text, [a, b])
        rows.append((0 if hot else 1, i, "- " + "".join(bits)))
    rows.sort(key=lambda r: (r[0], r[1]))
    return "\n".join(r[2] for r in rows[:20])


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

    # 本章在写什么：台阶 + 本卷大纲 + 细纲 + 上一章结尾 + 人工强调。
    # 各个清单段都先按这段文本判「本章相关」，再决定谁先进预算——预算不够时
    # 丢的必须是这本书此刻用不到的人/地点/术语，而不是文件里排在后面的。
    tail = prev_tail(root, n)
    outline_title, outline_beats = "", ""
    for row in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))):
        if _num(row.get("chapter")) == n:
            outline_title = _text(row.get("title"))
            parts = [str(x) for x in (row.get("beats") or []) if _text(x)]
            parts += [str(x) for x in (row.get("mustInclude") or []) if _text(x)]
            outline_beats = " ".join(parts)
            break
    focus_text = "\n".join(filter(None, [
        _stage_text(stage_row), volume_block, tail, outline_title, outline_beats,
        " ".join(_focus_lines(focus)),
    ]))
    recent = _recent_cast(root, n)

    # 伏笔
    fs_this, fs_this_count, fs_open, fs_open_count, fs_open_kept = _foreshadow_sections(root, n)

    # 人物
    chars, char_count, char_kept = _character_text(bible, focus_text=focus_text, recent=recent)
    names = _names(bible)
    state, state_kept, state_total = "", 0, 0
    if names:
        state_names = _rank_names(names, focus_text, recent)
        state_text = character_state(root, chapter=n, names=state_names)["text"]
        state_records = _records(state_text)
        state_total = len(state_records)
        state, state_kept = _pack(
            state_records,
            int(SECTION_LIMITS.get("character-state") or SECTION_LIMIT),
            [_brief(r) for r in state_records],
        )
    relations = _relation_text(
        effective_relations(root, bible, before_chapter=n), names, focus_text=focus_text,
    )
    gaps, gap_count = _info_gap_text(bible, focus_text=focus_text)
    cont_state = continuity_trail_text(bible)

    # 世界
    rules, rule_count, rule_kept = _rule_text(bible, focus_text=focus_text)
    world, world_count = _world_text(bible, project, focus_text=focus_text)
    factions, faction_count, faction_kept = _faction_text(bible, focus_text=focus_text)
    locations, location_count, location_kept = _location_text(bible, focus_text=focus_text)
    items, item_count, item_kept = _item_text(bible, focus_text=focus_text, recent=recent)
    power, power_count = _power_text(bible)
    society, society_count = _society_text(bible)
    history, history_count, history_kept = _history_text(bible, focus_text=focus_text)
    glossary, glossary_count, glossary_kept = _glossary_text(bible, focus_text=focus_text)

    # 前情：近 8 章详细 + 更早一章一句（已存档摘要折进这一层，不再单独占一段）
    chap_mem, chap_mem_count = _chapter_memory_text(root, n, focus)
    vol_mem = volume_memory(root, chapter=n)["text"]
    timeline, timeline_count = _timeline_text(root)

    # 写法
    style_text = _style_text(bible, project, stage, samples=effective.get("styleSamples", True))
    platform_text = platform_brief(project.get("platform")) if effective.get("platform", True) else ""
    nuewen_on = bool(effective.get("nuewen"))

    focus_lines = _focus_lines(focus)
    title = outline_title

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
                 text=fs_open, count=fs_open_count, source="伏笔账", missing=not fs_open,
                 kept=fs_open_kept),
        _section("characters", "人物", "人物卡",
                 text=chars, count=char_count, source="bible.characters", missing=not chars,
                 kept=char_kept),
        _section("character-state", "人物", "人物当前状态",
                 text=state, count=state_total, source="ledger/memory", missing=not state,
                 kept=state_kept),
        _section("continuity-state", "人物", "位置轨迹与转手",
                 text=cont_state, count=_count_lines(cont_state), source="bible 人物/物品（写后回写）",
                 missing=not cont_state, optional=True),
        _section("relations", "人物", "人物关系",
                 text=relations, count=_count_lines(relations),
                 source="bible.relations + ledger/relations.json", missing=not relations),
        _section("info-gaps", "人物", "信息差",
                 text=gaps, count=gap_count, source="bible.infoGaps", missing=not gaps, optional=True),
        _section("rules", "世界", "规则",
                 text=rules, count=rule_count, source="bible.rules", missing=not rules,
                 kept=rule_kept),
        _section("world", "世界", "世界观",
                 text=world, count=world_count, source="大纲/世界观", missing=not world),
        _section("factions", "世界", "势力",
                 text=factions, count=faction_count, source="bible.factions", missing=not factions,
                 kept=faction_kept),
        _section("locations", "世界", "地点",
                 text=locations, count=location_count, source="bible.locations", missing=not locations,
                 kept=location_kept),
        _section("items", "世界", "物品",
                 text=items, count=item_count, source="bible.items", missing=not items,
                 kept=item_kept),
        _section("power-system", "世界", "力量体系",
                 text=power, count=power_count, source="bible.powerSystem",
                 missing=not power, optional=True),
        _section("society", "世界", "社会常识",
                 text=society, count=society_count, source="bible.society",
                 missing=not society, optional=True),
        _section("history", "世界", "大事记",
                 text=history, count=history_count, source="bible.history",
                 missing=not history, optional=True, kept=history_kept),
        _section("glossary", "世界", "术语表",
                 text=glossary, count=glossary_count, source="bible.glossary",
                 missing=not glossary, optional=True, kept=glossary_kept),
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
            kept, count = int(section.get("kept") or 0), int(section.get("count") or 0)
            if section.get("truncated"):
                if 0 < kept < count:
                    head += f"（已按预算收口：展开 {kept}/{count} 条，未展开的只留名字，别当成不存在）"
                else:
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
