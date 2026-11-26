"""组织架构 + 职业等级体系。

这两层和「势力」不是一回事：
- ``bible.factions`` 回答「世界上有哪些势力、彼此什么态度」；
- ``bible.organizations`` 回答「一个势力内部谁管谁、谁在哪个位置」；
- ``bible.careers`` 回答「这本书里升一级靠什么，等级台阶长什么样」。

组织与职业由模型从已有设定里整理，只补空字段、不覆盖作者手写的内容。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..db import now_iso
from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from ..store import load_bible, load_project, project_lock, save_bible


def _text(value: Any, limit: int = 0) -> str:
    s = " ".join(str(value or "").split())
    return s[:limit] if limit and len(s) > limit else s


def _key(value: Any) -> str:
    return re.sub(r"[\s·・\-—_/、，,。.（）()「」『』【】]+", "", str(value or "")).lower()


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [x for x in (value or []) if isinstance(x, dict)]


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(x).strip() for x in (value or []) if str(x).strip()]


def _parse_json(raw: Any) -> dict[str, Any] | None:
    text = strip_fence(str(raw or "")).strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _material(project: dict[str, Any], bible: dict[str, Any]) -> str:
    chars = "；".join(
        f"{_text(c.get('name'))}（{_text(c.get('role') or c.get('rolePosition')) or '身份未定'}）"
        for c in _dicts(bible.get("characters"))[:30]
        if _text(c.get("name"))
    )
    factions = "；".join(
        f"{_text(f.get('name'))}（{_text(f.get('nature')) or '性质未定'}；首领 {_text(f.get('leader')) or '未定'}）"
        for f in _dicts(bible.get("factions"))[:20]
        if _text(f.get("name"))
    )
    power = bible.get("powerSystem") or {}
    levels = "、".join(_text(x.get("name")) for x in _dicts(power.get("levels"))[:12] if _text(x.get("name")))
    orgs = "；".join(_text(o.get("name")) for o in _dicts(bible.get("organizations"))[:30] if _text(o.get("name")))
    careers = "；".join(_text(c.get("name")) for c in _dicts(bible.get("careers"))[:20] if _text(c.get("name")))
    return "\n".join([
        f"书名：{_text(project.get('title'))}",
        f"题材：{_text(project.get('genre'))}",
        f"一句话：{_text(project.get('logline') or project.get('spine'))}",
        f"人物：{chars or '—'}",
        f"势力：{factions or '—'}",
        f"力量体系：{_text(power.get('name'))}；台阶：{levels or '—'}",
        f"已有组织：{orgs or '—'}",
        f"已有职业：{careers or '—'}",
    ])


def _messages(project: dict[str, Any], bible: dict[str, Any]) -> list[dict[str, str]]:
    system = "\n".join([
        "你是长篇小说的设定编辑。请从已有设定里整理两层结构，只输出 JSON。",
        "",
        "1. organizations（组织架构）：",
        "   - 每个组织写 name / faction（所属势力，必须来自「势力」列表；不属于任何势力就留空）",
        "     / kind（门派、公司、家族、军队、教会、学院…）/ parent（上级组织名，顶层留空）",
        "     / leader（首领）/ summary（一句话职能）/ members。",
        "   - 顶层组织通常就是势力本身：name 与势力同名时，faction 也写这个势力名，leader 和 summary 留空——",
        "     首领与介绍以势力卡为准，不要另写一份，避免两处说法打架。",
        "   - 子组织（在势力内部）才写自己的 leader / summary。",
        "   - members 是人物的职位：name（必须用已有的人物名，没有就留空）、role（职位）、rank（位阶/等级）；",
        "     代表人物已经在势力卡里，members 只记座位，不要重复抄一遍。",
        "   - parent 必须指向另一个 organization 的 name；组织层级最多三层，不要循环。",
        "   - 不要把整个世界写成一个组织；没有明确上下级就都做顶层。",
        "",
        "2. careers（职业等级体系）：",
        "   - 每条写 name / summary / appliesTo（适用人群或组织）/ advancement（怎么晋升）",
        "     / levels（从低到高，每级 name / rank / trait / gap）。",
        "   - 力量体系已经有等级台阶时，职业体系要和它对齐，不要另造一套冲突的等级。",
        "   - 现代题材写职级/军衔/警衔；玄幻写门派位阶/官职；没有等级体系就输出空数组。",
        "",
        "3. 只整理设定里能支撑的内容，不要发明新人物、新势力；人物名必须来自「人物」列表。",
        "4. 已有同名组织/职业只补空字段，不覆盖已有内容。",
        "",
        "输出 JSON：",
        "{",
        '  "organizations":[{"name":"","faction":"","kind":"","parent":"","leader":"","summary":"",',
        '    "members":[{"name":"","role":"","rank":""}]}],',
        '  "careers":[{"name":"","summary":"","appliesTo":[],"advancement":"",',
        '    "levels":[{"name":"","rank":"","trait":"","gap":""}]}]',
        "}",
    ])
    user = "\n".join([
        "以下是这本书的已有素材，请整理组织架构与职业等级，只输出 JSON：",
        "",
        _material(project, bible),
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _merge_org(
    rows: list[dict[str, Any]],
    incoming: dict[str, Any],
    factions: dict[str, str] | None = None,
) -> str:
    """Returns "added" / "filled" / "" — counts need to tell the two apart。

    ``factions`` 是「势力名 key → 规范名」。顶层组织与势力同名时，首领和介绍
    以势力卡为准，这里不落第二份；子组织仍保留自己的 leader / summary。
    """
    name = _text(incoming.get("name"), 60)
    if not name:
        return ""
    known = factions or {}
    raw_faction = _text(incoming.get("faction"), 60) or (name if _key(name) in known else "")
    faction = known.get(_key(raw_faction), raw_faction)
    # 组织名就是势力名：这是势力的「内部座位表」，不是另一个独立组织。
    is_faction_itself = bool(faction) and _key(faction) == _key(name)

    existing = next((x for x in rows if _key(x.get("name")) == _key(name)), None)
    if existing is None:
        members = []
        for m in _dicts(incoming.get("members"))[:80]:
            who = _text(m.get("name"), 40)
            if not who:
                continue
            members.append({
                "name": who,
                "role": _text(m.get("role"), 40),
                "rank": _text(m.get("rank"), 40),
            })
        rows.append({
            "name": name,
            "faction": faction,
            "kind": _text(incoming.get("kind"), 30),
            "parent": _text(incoming.get("parent"), 60),
            "leader": "" if is_faction_itself else _text(incoming.get("leader"), 40),
            "summary": "" if is_faction_itself else _text(incoming.get("summary"), 160),
            "members": members,
        })
        return "added"

    filled = False
    fields = ["kind", "parent"] if is_faction_itself else ["kind", "parent", "leader", "summary"]
    for field in fields:
        value = _text(incoming.get(field))
        if value and not _text(existing.get(field)):
            existing[field] = value[:160]
            filled = True
    if faction and not _text(existing.get("faction")):
        existing["faction"] = faction
        filled = True
    if not existing.get("members"):
        members = [
            {"name": _text(m.get("name"), 40), "role": _text(m.get("role"), 40), "rank": _text(m.get("rank"), 40)}
            for m in _dicts(incoming.get("members"))[:80] if _text(m.get("name"))
        ]
        if members:
            existing["members"] = members
            filled = True
    return "filled" if filled else ""


def _merge_career(rows: list[dict[str, Any]], incoming: dict[str, Any]) -> str:
    name = _text(incoming.get("name"), 60)
    if not name:
        return ""
    existing = next((x for x in rows if _key(x.get("name")) == _key(name)), None)
    levels = [
        {
            "name": _text(x.get("name"), 40),
            "rank": _text(x.get("rank"), 40),
            "trait": _text(x.get("trait"), 120),
            "gap": _text(x.get("gap"), 120),
        }
        for x in _dicts(incoming.get("levels"))[:30] if _text(x.get("name"))
    ]
    if existing is None:
        rows.append({
            "name": name,
            "summary": _text(incoming.get("summary"), 160),
            "appliesTo": _str_list(incoming.get("appliesTo"))[:12],
            "advancement": _text(incoming.get("advancement"), 160),
            "levels": levels,
        })
        return "added"
    filled = False
    for field in ("summary", "advancement"):
        value = _text(incoming.get(field))
        if value and not _text(existing.get(field)):
            existing[field] = value
            filled = True
    if not existing.get("appliesTo"):
        values = _str_list(incoming.get("appliesTo"))
        if values:
            existing["appliesTo"] = values[:12]
            filled = True
    if not existing.get("levels") and levels:
        existing["levels"] = levels
        filled = True
    return "filled" if filled else ""


def hierarchy_view(root: str | os.PathLike) -> dict[str, Any]:
    """给前端画图用的组织/职业结构：parent 解析成 id，并标出写坏的地方。"""
    bible = load_bible(root)
    chars = {
        _key(c.get("name")): _text(c.get("name"))
        for c in _dicts(bible.get("characters")) if _text(c.get("name"))
    }
    orgs = _dicts(bible.get("organizations"))
    ids = {_key(o.get("name")): i for i, o in enumerate(orgs) if _text(o.get("name"))}
    factions = {
        _key(f.get("name")): f
        for f in _dicts(bible.get("factions")) if _text(f.get("name"))
    }
    warnings: list[str] = []
    nodes = []
    for i, o in enumerate(orgs):
        name = _text(o.get("name"))
        if not name:
            continue
        parent_name = _text(o.get("parent"))
        parent_id = ids.get(_key(parent_name))
        if parent_name and parent_id is None:
            warnings.append(f"「{name}」的上级「{parent_name}」不在组织列表里")
        if parent_id == i:
            warnings.append(f"「{name}」的上级写成了自己")
            parent_id = None

        # 所属势力：没填就按「组织名 == 势力名」认爹，兼容旧数据。
        raw_faction = _text(o.get("faction")) or (name if _key(name) in factions else "")
        faction = factions.get(_key(raw_faction))
        if raw_faction and faction is None:
            warnings.append(f"「{name}」的所属势力「{raw_faction}」不在势力列表里")
        faction_name = _text((faction or {}).get("name")) or raw_faction
        is_faction_itself = bool(faction) and _key(faction_name) == _key(name)

        own_leader = _text(o.get("leader"))
        own_summary = _text(o.get("summary"))
        leader, summary = own_leader, own_summary
        leader_source = "org" if own_leader else ""
        summary_source = "org" if own_summary else ""
        if is_faction_itself:
            # 顶层组织就是势力本身：首领与介绍以势力卡为准，避免同一事实两处说法。
            faction_leader = _text(faction.get("leader"), 40)
            faction_summary = _text(faction.get("summary") or faction.get("text"), 200)
            if faction_leader:
                if own_leader and _key(own_leader) != _key(faction_leader):
                    warnings.append(f"「{name}」的首领与势力卡不一致，已按势力卡显示")
                leader, leader_source = faction_leader, "faction"
            if faction_summary:
                summary, summary_source = faction_summary, "faction"

        members = []
        for m in _dicts(o.get("members")):
            who = _text(m.get("name"))
            if not who:
                continue
            if _key(who) not in chars:
                warnings.append(f"「{name}」的成员「{who}」不在人物列表里")
            members.append({
                "name": chars.get(_key(who), who),
                "role": _text(m.get("role")),
                "rank": _text(m.get("rank")),
                "known": _key(who) in chars,
            })
        nodes.append({
            "id": i,
            "name": name,
            "kind": _text(o.get("kind")),
            "parent": parent_name,
            "parentId": parent_id,
            "faction": faction_name,
            "factionId": _key(faction_name) if faction else None,
            "linked": bool(faction),
            "isFactionItself": is_faction_itself,
            "leader": leader,
            "leaderSource": leader_source,
            "summary": summary,
            "summarySource": summary_source,
            "members": members,
        })

    # 环检测：顺着 parent 走，走回自己就砍掉 parent。
    by_id = {n["id"]: n for n in nodes}
    for node in nodes:
        seen = {node["id"]}
        cur = node
        while cur.get("parentId") is not None and cur["parentId"] in by_id:
            pid = cur["parentId"]
            if pid in seen:
                warnings.append(f"「{node['name']}」的上级链成环，已断开")
                node["parentId"] = None
                break
            seen.add(pid)
            cur = by_id[pid]

    careers = []
    for c in _dicts(bible.get("careers")):
        name = _text(c.get("name"))
        if not name:
            continue
        careers.append({
            "name": name,
            "summary": _text(c.get("summary")),
            "appliesTo": _str_list(c.get("appliesTo")),
            "advancement": _text(c.get("advancement")),
            "levels": [
                {
                    "name": _text(x.get("name")),
                    "rank": _text(x.get("rank")),
                    "trait": _text(x.get("trait")),
                    "gap": _text(x.get("gap")),
                }
                for x in _dicts(c.get("levels")) if _text(x.get("name"))
            ],
        })
    return {
        "organizations": nodes,
        "careers": careers,
        "warnings": list(dict.fromkeys(warnings)),
        "counts": {"organizations": len(nodes), "careers": len(careers)},
    }


def generate_hierarchy(
    root: str | os.PathLike,
    *,
    model: str | None = None,
    on_delta=None,
) -> dict[str, Any]:
    """让模型从人物/势力/力量体系里整理组织架构与职业等级。"""
    project = load_project(root) or {}
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    bible = load_bible(root)
    result = chat(
        _messages(project, bible),
        model=model,
        temperature=0.3,
        max_tokens=8000,
        timeout=300,
        reasoning=reasoning_for("settings"),
        on_delta=on_delta,
    )
    parsed = _parse_json(result.get("text"))
    if parsed is None:
        raise LLMError(f"模型没有返回可解析的组织/职业 JSON：{str(result.get('text'))[:200]}")

    with project_lock(root):
        current = load_bible(root)
        orgs = _dicts(current.get("organizations"))
        careers = _dicts(current.get("careers"))
        factions = {
            _key(f.get("name")): _text(f.get("name"))
            for f in _dicts(current.get("factions")) if _text(f.get("name"))
        }
        added_org = filled_org = added_career = filled_career = 0
        for row in _dicts(parsed.get("organizations"))[:80]:
            outcome = _merge_org(orgs, row, factions)
            if outcome == "added":
                added_org += 1
            elif outcome == "filled":
                filled_org += 1
        for row in _dicts(parsed.get("careers"))[:40]:
            outcome = _merge_career(careers, row)
            if outcome == "added":
                added_career += 1
            elif outcome == "filled":
                filled_career += 1
        current["organizations"] = orgs
        current["careers"] = careers
        save_bible(root, current)

    total = added_org + added_career
    return {
        "ok": True,
        "added": {"organizations": added_org, "careers": added_career},
        "filled": {"organizations": filled_org, "careers": filled_career},
        "organizations": len(orgs),
        "careers": len(careers),
        "summary": (
            f"整理出 {len(orgs)} 个组织、{len(careers)} 套职业等级"
            + (f"（新增 {total} 条）" if total else "（没有新增，已有内容保持不动）")
        ),
        "model": str(result.get("model") or model or ""),
        "at": now_iso(),
    }
