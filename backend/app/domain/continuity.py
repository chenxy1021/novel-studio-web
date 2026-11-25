"""连续性：规则的「可违反程度」、人物位置轨迹、物品持有链。

写长篇最常见的三类「吃书」都出在这里：

- 人物漂移：上一章还在城西，这一章没交代就到了城东；
- 物品瞬移：断桨在甲板上，三天后突然出现在别人手里；
- 规则失忆：作者记不清哪条能破、破了要付什么代价。

本模块只做确定性的事：给规则归类、把章记忆里抽出的「谁去了哪」「谁拿了什么」
并回 bible（只前进不覆盖历史），以及给提示词渲染「截至第 N 章」的事实行。
模型调用留在 ``settings_gen`` / ``memory_gen``，这里不调模型。
"""

from __future__ import annotations

import os
from typing import Any

from ..store import load_bible, project_lock, save_bible

# --------------------------------------------------------------------------- #
# 规则：可违反程度
# --------------------------------------------------------------------------- #

#: 四类规则，按「能不能破、破了付什么」排：
#: 铁律 = 破不了（世界不成立）；契约 = 能破，但必付代价；
#: 惯例 = 能破，代价是社会性的；谣言 = 人物以为是规则，其实不成立。
ENFORCE_CLASSES = ("铁律", "契约", "惯例", "谣言")

ENFORCE_HINTS = {
    "铁律": "不可违反：违反后人物或世界不成立，只能绕，不能破",
    "契约": "可以违反，但必须当场付出明确代价（反噬、折寿、失忆、违约反扑）",
    "惯例": "可以违反，代价是社会性的（被逐出、失去信誉、得罪势力），不是天谴",
    "谣言": "人物以为是规则，其实不成立；可以打破，打破后揭示真相",
}

_LEVEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("铁律", "铁律"), ("铁则", "铁律"), ("不可违反", "铁律"), ("硬规则", "铁律"),
    ("法则", "铁律"), ("定律", "铁律"), ("物理", "铁律"), ("法律", "铁律"),
    ("契约", "契约"), ("誓约", "契约"), ("代价", "契约"), ("可违反", "契约"),
    ("交易", "契约"), ("反噬", "契约"), ("血契", "契约"),
    ("惯例", "惯例"), ("习俗", "惯例"), ("规矩", "惯例"), ("门规", "惯例"),
    ("潜规则", "惯例"), ("社会", "惯例"), ("道德", "惯例"), ("传统", "惯例"),
    ("谣言", "谣言"), ("迷信", "谣言"), ("误传", "谣言"), ("传说", "谣言"),
    ("以为", "谣言"), ("伪", "谣言"),
)


def rule_enforce(rule: dict[str, Any]) -> str:
    """取规则的类别；老数据只有 ``level``（铁律/惯例/谣言）也能对上。"""
    raw = str(rule.get("enforce") or rule.get("level") or "").strip()
    for needle, label in _LEVEL_ALIASES:
        if needle in raw:
            return label
    return "铁律"


def rule_enforce_hint(rule: dict[str, Any]) -> str:
    return ENFORCE_HINTS[rule_enforce(rule)]


def rule_line(rule: dict[str, Any]) -> str:
    """规则的一行提示词写法：类别 + 条文 + 代价 + 边界。"""
    name = str(rule.get("name") or rule.get("text") or "").strip()
    if not name:
        return ""
    kind = rule_enforce(rule)
    bits = [f"[{kind}] {name}"]
    if rule.get("cost"):
        bits.append(f"违反代价:{rule.get('cost')}")
    if rule.get("boundary"):
        bits.append(f"边界/漏洞:{rule.get('boundary')}")
    if rule.get("enforcer"):
        bits.append(f"执行者:{rule.get('enforcer')}")
    return "- " + "；".join(bits)


# --------------------------------------------------------------------------- #
# 人物 / 物品行
# --------------------------------------------------------------------------- #


def _text(value: Any) -> str:
    return str(value or "").strip()


def location_history(character: dict[str, Any]) -> list[dict[str, Any]]:
    """人物的移动记录，容忍老数据写成字符串。"""
    raw = character.get("locationHistory")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                place = _text(row.get("place") or row.get("to"))
                if place:
                    out.append({"chapter": _num(row.get("chapter")), "place": place, "note": _text(row.get("note"))})
            elif _text(row):
                out.append({"chapter": 0, "place": _text(row), "note": ""})
    return out


_STATUS_ALIASES: tuple[tuple[str, str], ...] = (
    ("在场", "active"), ("活着", "active"), ("存活", "active"), ("active", "active"),
    ("alive", "active"), ("出场", "active"),
    ("死亡", "dead"), ("死了", "dead"), ("身亡", "dead"), ("死", "dead"),
    ("dead", "dead"), ("阵亡", "dead"),
    ("失踪", "missing"), ("下落不明", "missing"), ("missing", "missing"),
    ("退场", "exited"), ("已退场", "exited"), ("离开", "exited"), ("exited", "exited"),
)
_GONE_STATUS = {"dead", "missing", "exited"}


def normalize_status(value: Any) -> str:
    """把「死了 / 死亡 / dead」都归到 active|dead|missing|exited；认不出返回空串。"""
    raw = _text(value)
    if not raw:
        return ""
    for needle, label in _STATUS_ALIASES:
        if needle in raw:
            return label
    return ""


def status_history(character: dict[str, Any]) -> list[dict[str, Any]]:
    """人物的状态变化，按章排序；容忍老数据写成字符串。"""
    raw = character.get("statusLog")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            status = normalize_status(row.get("status"))
            if not status:
                continue
            out.append({
                "chapter": _num(row.get("chapter")),
                "status": status,
                "note": _text(row.get("note")),
            })
    return sorted(out, key=lambda r: r["chapter"])


def character_status_at(character: dict[str, Any], before_chapter: int | None = None) -> dict[str, Any]:
    """出场状态、当前状态、最终状态和状态变化。

    ``status`` 一直是「当前状态」：老数据里它写的就是最新状态，状态变化回写时也跟着往前推；
    ``appearanceStatus`` 记出场那一刻；``finalStatus`` 是按大纲结局提前定的。
    ``before_chapter`` 按「写第 n 章时已知」的口径：第 n 章自己的变化还没发生。
    """
    log = status_history(character)
    appearance = normalize_status(character.get("appearanceStatus"))
    final = normalize_status(character.get("finalStatus"))
    fallback_at = _num(character.get("statusAt")) or _num(character.get("exitChapter")) or _num(character.get("firstChapter"))
    if before_chapter:
        earlier = [r for r in log if r["chapter"] < before_chapter]
        if earlier:
            current, current_at = earlier[-1]["status"], earlier[-1]["chapter"]
        elif log:
            # 第一条变化之前就是出场时的状态；没记录出场状态就当作不知道，不硬判。
            current, current_at = appearance, _num(character.get("firstChapter"))
        else:
            # 没有按章轨迹（老数据 / 补进设定填的）：只能用当前状态。
            current, current_at = normalize_status(character.get("status")), fallback_at
    elif log:
        current, current_at = log[-1]["status"], log[-1]["chapter"]
    else:
        current, current_at = normalize_status(character.get("status")), fallback_at
    return {
        "appearance": appearance,
        "current": current,
        "currentAt": current_at,
        "final": final,
        "log": log,
    }


def _append_status(character: dict[str, Any], chapter: int, status: Any, note: str) -> bool:
    """记一次状态变化。同一章重跑只留最后一条；和这一刻一样就不记。"""
    label = normalize_status(status)
    if not label or chapter <= 0:
        return False
    existing = [r for r in status_history(character) if r["chapter"] == chapter]
    if existing and existing[-1]["status"] == label and existing[-1]["note"] == note:
        return False  # 原样重放（补进设定/重算都跑一遍），不算新变化
    kept = [r for r in status_history(character) if r["chapter"] != chapter]
    previous = kept[-1]["status"] if kept else (
        normalize_status(character.get("appearanceStatus")) or normalize_status(character.get("status"))
    )
    if label == previous:
        return False
    if not kept and not normalize_status(character.get("appearanceStatus")):
        # 第一次记变化：变化前的 status 就是出场时的状态，先存下来再往前推。
        character["appearanceStatus"] = previous
    kept.append({"chapter": chapter, "status": label, "note": note})
    character["statusLog"] = sorted(kept, key=lambda r: r["chapter"])[-40:]
    character["status"] = label
    character["statusAt"] = chapter
    if label in _GONE_STATUS:
        if not _num(character.get("exitChapter")):
            character["exitChapter"] = chapter
    elif label == "active":
        # 死过的人又出场（诈死、活回来）：退场章清掉，状态轨迹里留着这段。
        character["exitChapter"] = 0
    return True


def character_location(character: dict[str, Any]) -> tuple[str, int]:
    """(当前位置, 截至第几章)；轨迹里最新的位置优先于老字段。"""
    hist = location_history(character)
    if hist:
        last = max(hist, key=lambda r: r["chapter"])
        if last["place"]:
            return last["place"], last["chapter"]
    return _text(character.get("location")), _num(character.get("locationAt"))


def character_line(character: dict[str, Any]) -> str:
    """人物卡的单行渲染；字段按「写正文真会用到的」排序。"""
    name = _text(character.get("name"))
    if not name:
        return ""
    bits: list[str] = []
    role = _text(character.get("rolePosition") or character.get("role"))
    if role:
        bits.append(f"身份:{role}")
    tier = _text(character.get("importance") or character.get("tier"))
    if tier:
        bits.append(f"重要度:{tier}")
    aliases = character.get("aliases")
    if isinstance(aliases, list):
        names = [_text(a) for a in aliases if _text(a)]
        if names:
            bits.append(f"别名:{'、'.join(names)}")
    for key, label in (("gender", "性别"), ("age", "年龄"), ("race", "种族")):
        if _text(character.get(key)):
            bits.append(f"{label}:{_text(character.get(key))}")
    if character.get("personality"):
        bits.append(f"性格:{character.get('personality')}")
    if character.get("appearance"):
        bits.append(f"外形:{character.get('appearance')}")
    if character.get("want"):
        bits.append(f"想要:{character.get('want')}")
    if character.get("fear"):
        bits.append(f"怕:{character.get('fear')}")
    if character.get("bottomLine"):
        bits.append(f"底线:{character.get('bottomLine')}")
    if character.get("flaw"):
        bits.append(f"弱点:{character.get('flaw')}")
    if character.get("secret"):
        bits.append(f"秘密:{character.get('secret')}")
    if character.get("voice"):
        bits.append(f"说话:{character.get('voice')}")
    ability = _text(character.get("ability"))
    if ability:
        extra = "、".join(x for x in (
            f"限:{_text(character.get('abilityLimit'))}" if character.get("abilityLimit") else "",
            f"代价:{_text(character.get('abilityCost'))}" if character.get("abilityCost") else "",
        ) if x)
        bits.append(f"本事:{ability}" + (f"（{extra}）" if extra else ""))
    st = character_status_at(character)
    if st["current"]:
        label = _status_label(st["current"])
        if st["log"] and st["appearance"] and st["current"] != st["appearance"]:
            label = f"{_status_label(st['appearance'])}→{label}（第{st['currentAt']}章起）"
        elif st["log"]:
            label = f"{label}（第{st['currentAt']}章起）"
        bits.append(f"状态:{label}")
    if st["final"] and st["final"] != st["current"]:
        bits.append(f"最终:{_status_label(st['final'])}（按大纲结局，还没写到）")
    first, exit_at = _num(character.get("firstChapter")), _num(character.get("exitChapter"))
    if first:
        bits.append(f"首次登场:第{first}章")
    if exit_at:
        bits.append(f"退场:第{exit_at}章")
    place, as_of = character_location(character)
    if place:
        bits.append(f"位置:{place}" + (f"（截至第{as_of}章）" if as_of else ""))
    goal = _text(character.get("currentGoal"))
    if goal:
        bits.append(f"当前目标:{goal}")
    return f"【人物·{name}】" + "；".join(bits)


_STATUS_LABELS = {
    "active": "在场", "在场": "在场",
    "dead": "死亡", "死亡": "死亡",
    "missing": "失踪", "失踪": "失踪",
    "exited": "已退场", "退场": "已退场", "已退场": "已退场",
}


def _status_label(value: Any) -> str:
    s = _text(value)
    return _STATUS_LABELS.get(s, s)


def transfer_log(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw = item.get("transferLog")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, dict):
                out.append({
                    "chapter": _num(row.get("chapter")),
                    "from": _text(row.get("from")),
                    "to": _text(row.get("to") or row.get("holder")),
                    "note": _text(row.get("note")),
                })
            elif _text(row):
                out.append({"chapter": 0, "from": "", "to": _text(row), "note": ""})
    return out


def item_line(item: dict[str, Any]) -> str:
    name = _text(item.get("name"))
    if not name:
        return ""
    bits: list[str] = []
    if item.get("type"):
        bits.append(_text(item.get("type")))
    if item.get("function"):
        bits.append(f"作用:{_text(item.get('function'))}")
    if item.get("limit"):
        bits.append(f"限制:{_text(item.get('limit'))}")
    if item.get("cost"):
        bits.append(f"代价:{_text(item.get('cost'))}")
    holder = _text(item.get("holder"))
    at = _num(item.get("holderAt"))
    if holder:
        bits.append(f"持有:{holder}" + (f"（截至第{at}章）" if at else ""))
    elif item.get("location"):
        bits.append(f"所在:{_text(item.get('location'))}")
    if item.get("state"):
        bits.append(f"状态:{_text(item.get('state'))}")
    if item.get("whoKnows"):
        bits.append(f"谁知道:{_text(item.get('whoKnows'))}")
    return f"【物品·{name}】" + "；".join(bits)


# --------------------------------------------------------------------------- #
# 章落盘后回写：位置 / 物品
# --------------------------------------------------------------------------- #


def _num(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _name_key(value: Any) -> str:
    import re

    return re.sub(r"[\s·・\-—_/、，,。.（）()「」『』【】]+", "", str(value or "")).lower()


def _find(rows: Any, name: Any) -> dict[str, Any] | None:
    key = _name_key(name)
    if not key:
        return None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if _name_key(row.get("name")) == key:
            return row
        aliases = row.get("aliases")
        if isinstance(aliases, list) and any(_name_key(a) == key for a in aliases):
            return row
    return None


def _append_move(character: dict[str, Any], chapter: int, place: str, note: str) -> bool:
    hist = location_history(character)
    current, _ = character_location(character)
    # 已经在同一地点：不是移动，不记账（模型常把「本章在码头」也报成 move）。
    if current == place:
        if hist and hist[-1]["place"] == place:
            hist[-1]["chapter"] = max(hist[-1]["chapter"], chapter)
            character["locationHistory"] = hist[-40:]
            character["locationAt"] = max(_num(character.get("locationAt")), chapter)
            return False
        character["location"] = place
        character["locationAt"] = chapter
        character.setdefault("locationHistory", [])
        return False
    if hist:
        hist = [r for r in hist if not (r["chapter"] == chapter and r["place"] == place)]
    hist.append({"chapter": chapter, "place": place, "note": note})
    character["locationHistory"] = hist[-40:]
    character["location"] = place
    character["locationAt"] = chapter
    return True


def _append_transfer(item: dict[str, Any], chapter: int, to: str, note: str) -> bool:
    log = transfer_log(item)
    current = _text(item.get("holder"))
    if log and log[-1]["chapter"] == chapter and log[-1]["to"] == to:
        return False
    log.append({"chapter": chapter, "from": current, "to": to, "note": note})
    item["transferLog"] = log[-40:]
    item["holder"] = to
    item["holderAt"] = chapter
    return True


def apply_continuity(
    root: str | os.PathLike,
    chapter: int,
    *,
    moves: Any = None,
    item_changes: Any = None,
    faction_changes: Any = None,
    place_changes: Any = None,
    character_changes: Any = None,
) -> dict[str, int]:
    """把本章的「位置 / 人物状态 / 物品 / 势力 / 地点状态变化」并回 bible。

    只前进不覆盖：同一章同一地点/持有人不会重复记账，历史保留最近 40 条。
    失败不影响正文——调用方应当按 best-effort 处理。
    """
    n = _num(chapter)
    empty = {"moves": 0, "items": 0, "factions": 0, "places": 0, "characters": 0}
    if n <= 0:
        return empty
    char_rows = [
        x for x in (character_changes or [])
        if isinstance(x, dict) and _text(x.get("who")) and normalize_status(x.get("status"))
    ]
    move_rows = [x for x in (moves or []) if isinstance(x, dict) and _text(x.get("who")) and _text(x.get("to"))]
    item_rows = [x for x in (item_changes or []) if isinstance(x, dict) and _text(x.get("name"))]
    faction_rows = [
        x for x in (faction_changes or [])
        if isinstance(x, dict) and _text(x.get("name")) and _text(x.get("state"))
    ]
    place_rows = [
        x for x in (place_changes or [])
        if isinstance(x, dict) and _text(x.get("name")) and (_text(x.get("state")) or _text(x.get("occupied")))
    ]
    if not move_rows and not item_rows and not faction_rows and not place_rows and not char_rows:
        return empty

    touched_moves = touched_items = touched_factions = touched_places = touched_chars = 0
    with project_lock(root):
        bible = load_bible(root)
        chars = bible.get("characters") or []
        items = bible.get("items") or []
        factions = bible.get("factions") or []
        locations = bible.get("locations") or []
        for row in char_rows:
            c = _find(chars, row.get("who"))
            if c is None:
                continue
            if _append_status(c, n, row.get("status"), _text(row.get("note"))):
                touched_chars += 1
        for row in move_rows:
            c = _find(chars, row.get("who"))
            if c is None:
                continue
            if _append_move(c, n, _text(row.get("to")), _text(row.get("note"))):
                touched_moves += 1
        for row in item_rows:
            it = _find(items, row.get("name"))
            if it is None:
                continue
            holder = _text(row.get("holder"))
            state = _text(row.get("state"))
            if holder and _append_transfer(it, n, holder, _text(row.get("note"))):
                touched_items += 1
            elif holder:
                it["holderAt"] = n
            if state and _text(it.get("state")) != state:
                it["state"] = state
                it["stateAt"] = n
                touched_items += 1
        for row in faction_rows:
            faction = _find(factions, row.get("name"))
            if faction is None:
                continue
            state = _text(row.get("state"))
            if state and _text(faction.get("state")) != state:
                faction["state"] = state
                faction["stateAt"] = n
                touched_factions += 1
        for row in place_rows:
            location = _find(locations, row.get("name"))
            if location is None:
                continue
            changed = False
            state = _text(row.get("state"))
            if state and _text(location.get("state")) != state:
                location["state"] = state
                location["stateAt"] = n
                changed = True
            occupied = _text(row.get("occupied"))
            if occupied and _text(location.get("occupied")) != occupied:
                location["occupied"] = occupied
                changed = True
            if changed:
                touched_places += 1
        if touched_moves or touched_items or touched_factions or touched_places or touched_chars:
            save_bible(root, bible)
    return {
        "moves": touched_moves,
        "items": touched_items,
        "factions": touched_factions,
        "places": touched_places,
        "characters": touched_chars,
    }


def _prior_state(
    by_chapter: dict[int, dict[str, Any]],
    chapter: int,
    bucket: str,
    name: Any,
    field: str,
) -> tuple[str, int]:
    """本章之前最近一次写过这个字段的值；没有就返回 ("", 0)。"""
    key = _name_key(name)
    for ch in sorted((c for c in by_chapter if c < chapter), reverse=True):
        for row in (by_chapter[ch].get(bucket) or []):
            if not isinstance(row, dict) or _name_key(row.get("name")) != key:
                continue
            value = _text(row.get(field))
            if value:
                return value, ch
    return "", 0


def undo_chapter(root: str | os.PathLike, chapter: int) -> dict[str, int]:
    """撤回第 n 章并回 bible 的连续性变化（退稿时调用）。

    章记忆本身不删：``load_memory_rows`` 按正文索引过滤，章退掉后自然不再进前情，
    恢复废章时又自动生效。这里只把已经并进 bible 的「位置 / 转手 / 状态」退回去：
    删掉第 n 章的轨迹与转手记录，当前位置、持有者、势力与地点状态回退到本章之前
    最近一次记忆里的值。
    """
    n = _num(chapter)
    counts = {"moves": 0, "items": 0, "factions": 0, "places": 0, "characters": 0}
    if n <= 0:
        return counts
    # 这里不能走 load_memory_rows：它按正文索引过滤，而退回时这一章已经从索引里摘掉了。
    from ..store import read_jsonl
    from ..store.paths import project_path

    by_chapter: dict[int, dict[str, Any]] = {}
    for r in read_jsonl(project_path(root, "ledger/memory.jsonl")):
        if not isinstance(r, dict) or r.get("__corrupt"):
            continue
        if r.get("kind") in ("volume", "character-state") or r.get("chapter") is None:
            continue
        by_chapter[_num(r.get("chapter"))] = r
    row = by_chapter.get(n) or {}
    place_rows = [
        x for x in (row.get("placeStates") or []) if isinstance(x, dict) and _name_key(x.get("name"))
    ]

    with project_lock(root):
        bible = load_bible(root)
        chars = bible.get("characters") or []
        items = bible.get("items") or []
        factions = bible.get("factions") or []
        locations = bible.get("locations") or []
        for c in chars:
            if not isinstance(c, dict):
                continue
            log = status_history(c)
            if any(r["chapter"] == n for r in log):
                kept = [r for r in log if r["chapter"] != n]
                c["statusLog"] = kept
                # status 跟着退回本章之前的那一条；一条不剩就回到出场时的状态。
                if kept:
                    c["status"] = kept[-1]["status"]
                    c["statusAt"] = kept[-1]["chapter"]
                else:
                    appearance = normalize_status(c.get("appearanceStatus"))
                    if appearance:
                        c["status"] = appearance
                    c["statusAt"] = 0
                # 退场章跟着回退：这一章记的死亡/失踪撤掉后，退场章回到还剩下的第一条。
                gone = [r["chapter"] for r in kept if r["status"] in _GONE_STATUS]
                c["exitChapter"] = min(gone) if gone else 0
                counts["characters"] += 1
            hist = location_history(c)
            hit = any(_num(r.get("chapter")) == n for r in hist)
            if not hit and _num(c.get("locationAt")) != n:
                continue
            kept = [r for r in hist if _num(r.get("chapter")) != n]
            if hit:
                c["locationHistory"] = kept[-40:]
            if _num(c.get("locationAt")) == n:
                if kept:
                    c["location"] = _text(kept[-1].get("place"))
                    c["locationAt"] = _num(kept[-1].get("chapter"))
                else:
                    c["locationAt"] = 0
            counts["moves"] += 1

        for it in items:
            if not isinstance(it, dict):
                continue
            log = transfer_log(it)
            hit = any(_num(r.get("chapter")) == n for r in log)
            if hit or _num(it.get("holderAt")) == n:
                kept = [r for r in log if _num(r.get("chapter")) != n]
                if hit:
                    it["transferLog"] = kept[-40:]
                if _num(it.get("holderAt")) == n:
                    if kept:
                        it["holder"] = _text(kept[-1].get("to"))
                        it["holderAt"] = _num(kept[-1].get("chapter"))
                    else:
                        it["holderAt"] = 0
                counts["items"] += 1
            if _num(it.get("stateAt")) == n:
                value, at = _prior_state(by_chapter, n, "items", it.get("name"), "state")
                if value:
                    it["state"] = value
                    it["stateAt"] = at
                else:
                    it["stateAt"] = 0
                counts["items"] += 1

        for faction in factions:
            if not isinstance(faction, dict) or _num(faction.get("stateAt")) != n:
                continue
            value, at = _prior_state(by_chapter, n, "factionStates", faction.get("name"), "state")
            if value:
                faction["state"] = value
                faction["stateAt"] = at
            else:
                faction["stateAt"] = 0
            counts["factions"] += 1

        for location in locations:
            if not isinstance(location, dict):
                continue
            changed = False
            if _num(location.get("stateAt")) == n:
                value, at = _prior_state(by_chapter, n, "placeStates", location.get("name"), "state")
                if value:
                    location["state"] = value
                    location["stateAt"] = at
                else:
                    location["stateAt"] = 0
                changed = True
            mine = next(
                (x for x in place_rows if _name_key(x.get("name")) == _name_key(location.get("name"))),
                None,
            )
            if mine and _text(mine.get("occupied")):
                value, _ = _prior_state(by_chapter, n, "placeStates", location.get("name"), "occupied")
                location["occupied"] = value
                changed = True
            if changed:
                counts["places"] += 1

        if any(counts.values()):
            save_bible(root, bible)
    return counts


def reapply_chapter(root: str | os.PathLike, chapter: int) -> dict[str, int]:
    """废章恢复到正文后，把它记忆里的位置 / 转手 / 状态重新并回 bible。"""
    n = _num(chapter)
    empty = {"moves": 0, "items": 0, "factions": 0, "places": 0, "characters": 0}
    if n <= 0:
        return empty
    from .memory import load_memory_rows

    row = load_memory_rows(root)["byChapter"].get(n) or {}
    if not row:
        return empty
    return apply_continuity(
        root,
        n,
        moves=row.get("moves"),
        item_changes=row.get("items"),
        faction_changes=row.get("factionStates"),
        place_changes=row.get("placeStates"),
        character_changes=row.get("characterStates"),
    )


# --------------------------------------------------------------------------- #
# 提示词用：连贯性提醒
# --------------------------------------------------------------------------- #

CONTINUITY_RULES = (
    "人物位置以「位置/截至第 N 章」为准：没有交代移动过程，不要让人物出现在另一个地点。",
    "跨章移动允许，但正文必须交代时间与路程（走了多久、怎么走、途中发生什么），不能凭空切换。",
    "物品的持有者与状态同样以「截至第 N 章」为准；转手必须写清谁在什么时候、因为什么交出去。",
    "规则按类别处理：铁律只能绕不能破；契约可以破，但当场付代价；惯例违反要承担社会后果；谣言可以打破，打破时要揭示真相。",
)


def continuity_rules_text() -> str:
    return "\n".join(f"- {x}" for x in CONTINUITY_RULES)


def continuity_trail_text(bible: dict[str, Any]) -> str:
    """只给「轨迹 / 转手」这类卡片里没有的信息。

    当前位置与持有者已经在人物卡、物品行里各写了一遍；这里不再重复，
    避免同一事实在提示词里出现三次。
    """
    lines: list[str] = []
    for c in (bible.get("characters") or [])[:40]:
        if not isinstance(c, dict):
            continue
        hist = location_history(c)
        if not hist:
            continue
        tail = " → ".join(
            f"{r['place']}(第{r['chapter']}章)" if r["chapter"] else r["place"]
            for r in hist[-6:]
        )
        lines.append(f"- {_text(c.get('name'))} 轨迹：{tail}")
    for it in (bible.get("items") or [])[:40]:
        if not isinstance(it, dict):
            continue
        log = transfer_log(it)
        if not log:
            continue
        tail = "；".join(
            f"第{r['chapter']}章" + (f"从{r['from']}" if r["from"] else "") + f"到{r['to']}"
            for r in log[-4:]
            if r["to"]
        )
        if tail:
            lines.append(f"- {_text(it.get('name'))} 转手：{tail}")
    return "\n".join(lines)


def continuity_state_text(bible: dict[str, Any], chapter: int) -> str:
    """「截至第 N 章」的人物位置与物品去向；只列有记录的，避免整表灌进提示词。"""
    lines: list[str] = []
    for c in (bible.get("characters") or [])[:40]:
        if not isinstance(c, dict):
            continue
        place, as_of = character_location(c)
        if not place:
            continue
        hist = location_history(c)
        tail = " → ".join(f"{r['place']}(第{r['chapter']}章)" for r in hist[-4:] if r["chapter"])
        line = f"- {_text(c.get('name'))}：{place}"
        if as_of:
            line += f"（截至第{as_of}章）"
        if tail:
            line += f"；轨迹：{tail}"
        lines.append(line)
    for it in (bible.get("items") or [])[:40]:
        if not isinstance(it, dict):
            continue
        bits = []
        if it.get("holder"):
            bits.append(f"持有者：{_text(it.get('holder'))}")
            if _num(it.get("holderAt")):
                bits.append(f"（截至第{_num(it.get('holderAt'))}章）")
        elif it.get("location"):
            bits.append(f"所在：{_text(it.get('location'))}")
        if it.get("state"):
            bits.append(f"状态：{_text(it.get('state'))}")
        log = transfer_log(it)
        if log:
            last = log[-1]
            bits.append(f"最近转手：第{last['chapter']}章{'从' + last['from'] + '到' if last['from'] else '到'}{last['to']}")
        if bits:
            lines.append(f"- {_text(it.get('name'))}：" + "，".join(bits))
    return "\n".join(lines)


__all__ = [
    "ENFORCE_CLASSES",
    "ENFORCE_HINTS",
    "rule_enforce",
    "rule_enforce_hint",
    "rule_line",
    "character_line",
    "character_location",
    "location_history",
    "item_line",
    "transfer_log",
    "apply_continuity",
    "continuity_rules_text",
    "continuity_state_text",
    "continuity_trail_text",
]
