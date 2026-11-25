"""记忆生成：把已经写好的章/卷提炼成记忆账，供写新章时回填前情。

章记忆一次模型调用，产出「摘要 + 出场人物/地点 + 事件 + 人物知道 + 关系变化 +
故事内时间线」；卷记忆一次模型调用，产出本卷总述 + 六个维度。写账本就是
``append_jsonl``，读取仍按章取最新（``memory.load_memory_rows``）。

同 ``writing.py`` 的约定：模型调用在锁外，失败时一个字都不写；所有模型调用都
走 fastModel + 低温度，以便批量补齐时稳定、便宜。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from ..llm import LLMError, chat, strip_fence
from ..llm.settings import load_settings
from ..store import (
    append_jsonl,
    load_bible,
    load_project,
    project_lock,
    project_path,
    read_chapter,
    read_index,
    read_index_entry,
    read_jsonl,
)
from ..store.jsonl import fold_outline

MEMORY_FILE = "ledger/memory.jsonl"
TIMELINE_FILE = "ledger/timeline.jsonl"
OUTLINE_FILE = "ledger/outline.jsonl"

TIMELINE_KINDS = ("event", "foreshadow-plant", "foreshadow-payoff")
VOLUME_DIMS = ("mainline", "threads", "relations", "knowledge", "carryover", "drift")
VOLUME_DIM_HINTS = {
    "mainline": "主线推进到哪一步（对比大纲本卷任务）",
    "threads": "哪些支线/人物线被推进或丢下",
    "relations": "关系变化（谁和谁从什么变成什么）",
    "knowledge": "读者目前知道的真相 / 主角不知道的部分",
    "carryover": "必须带进下一卷的未收线索",
    "drift": "与大纲本卷任务不一致的地方",
}

MAX_PROSE_CHARS = 12000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _record_usage(root: str | os.PathLike, row: dict[str, Any]) -> None:
    append_jsonl(project_path(root, "metrics/usage.jsonl"), {"at": _now(), **row})


def _num(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _flag(value: Any) -> bool:
    """模型有时把布尔写成字符串；"false" 不能当 true。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).lower() in ("true", "1", "yes", "是", "回忆", "倒叙")


def _str_list(value: Any) -> list[str]:
    """模型偶尔把数组写成「甲、乙」；两种都收，去空去重。"""
    if isinstance(value, str):
        raw = re.split(r"[、,，;；\n]+", value)
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = []
    out: list[str] = []
    for item in raw:
        text = _text(item)
        if text and text not in out:
            out.append(text)
    return out


def _dict_list(value: Any, keys: tuple[str, ...]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        row = {k: _text(item.get(k)) for k in keys}
        if all(row.values()):
            out.append(row)
    return out


def _optional_rows(value: Any, keys: tuple[str, ...], required: str) -> list[dict[str, str]]:
    """势力 / 地点状态变化：required 字段必须有，其余字段能写就写。"""
    out: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        row = {k: _text(item.get(k)) for k in keys}
        if row.get(required):
            out.append({k: v for k, v in row.items() if v})
    return out


def _parse_json(text: Any) -> dict[str, Any] | None:
    """模型常带围栏或前后说明；只取第一个 { 到最后一个 } 之间的对象。"""
    s = strip_fence(str(text or ""))
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _outline_row(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    for row in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))):
        if _num(row.get("chapter")) == chapter:
            return row
    return None


def _chapter_text(root: str | os.PathLike, chapter: int) -> str:
    entry = read_index_entry(root, chapter)
    if not entry:
        raise ValueError(f"第{chapter}章还没有正文；先写完这一章再生成记忆")
    try:
        text = read_chapter(root, chapter) or ""
    except FileNotFoundError as e:
        raise ValueError(f"第{chapter}章索引存在，但正文文件不在了：{e}") from e
    if not text.strip():
        raise ValueError(f"第{chapter}章正文是空的；先写完这一章再生成记忆")
    return text


def _prev_memory(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    """上一章有记忆就用上一章；中间缺章时退回最近一章有记忆的。"""
    by_chapter = load_memory_rows(root)["byChapter"]
    for n in range(chapter - 1, 0, -1):
        row = by_chapter.get(n) or {}
        if row.get("summary"):
            return row
    return None


def load_memory_rows(root: str | os.PathLike) -> dict[str, Any]:
    """本地转调 memory.load_memory_rows，保持 ``memory_gen`` 的可替换面最小。"""
    from .memory import load_memory_rows as _load

    return _load(root)


def _settings_block(project: dict[str, Any], bible: dict[str, Any]) -> str:
    from .writing import _settings_brief

    chapter = _num(project.get("currentChapter")) + 1
    brief = _settings_brief(bible, chapter=chapter)
    return "\n".join([
        f"【作品】{_text(project.get('title'))}｜{_text(project.get('genre'))}｜{_text(project.get('tone'))}",
        f"【一句话】{_text(project.get('logline'))}",
        "【人物卡】", brief["chars"],
    ])


# --------------------------------------------------------------------------- #
# 章记忆
# --------------------------------------------------------------------------- #


def _chapter_messages(
    root: str | os.PathLike,
    project: dict[str, Any],
    bible: dict[str, Any],
    *,
    chapter: int,
    title: str,
    text: str,
    outline: dict[str, Any] | None,
    prev: dict[str, Any] | None,
) -> list[dict[str, str]]:
    beats = "\n".join(f"- {x}" for x in ((outline or {}).get("beats") or []))
    prev_block = "（这是开篇，没有上一章记忆）"
    if prev:
        mark = "〔回忆章，摘要里的时间和位置多在过去〕" if _flag(prev.get("isFlashback")) else ""
        prev_block = "\n".join(x for x in [
            f"上一章（第{_num(prev.get('chapter'))}章）{mark}摘要：{_text(prev.get('summary'))}",
            ("上一章关键事件：" + "；".join(str(e) for e in (prev.get("events") or []))) if prev.get("events") else "",
            ("上一章结束时：") + _text(prev.get("state")) if prev.get("state") else "",
        ] if x)

    system = (
        "你是长篇网文的记忆编辑。你要把已经写好的这一章提炼成给后续写作使用的记忆："
        "只记录正文里确实发生的事，不推测、不补充设定、不评价文笔。只输出一个 JSON 对象。"
    )
    user = f"""{_settings_block(project, bible)}

【本章】第 {chapter} 章《{title}》
【本章细纲】
{beats or '（没有细纲）'}

【上一章记忆（只作衔接参照）】
{prev_block}

【本章正文】
{text[:MAX_PROSE_CHARS]}

【提炼要求】
- summary：120-200 字，按发生顺序写清「谁 → 做了什么 → 结果变成什么」，不要抒情、不要评价。
- characters：本章真正出场的人物，用人物卡里的规范名。
- places：本章出现的地点，最多 6 个。
- events：按发生顺序的关键事件，3-8 条，每条一句话，要有动作和结果。
- storyTime：故事内时间（如「第 3 天 · 傍晚」），正文没写就留空字符串。回忆章要写「回忆里」的时间，
  例如「十年前 · 秋」，不要写成当前的第几天。
- isFlashback：本章是不是以回忆 / 倒叙为主（整章讲过去）。是就 true，正常推进 false；只是短暂闪回不算 true。
- state：章末状态，一到两句：主要人物此刻在哪、关键物品在谁手里、局势停在哪。不要复述剧情。
  回忆章写「回到现在」时的状态，不要把回忆里的旧位置当成此刻位置。
- knows：本章某个人物新知道了什么（谁、知道了什么），没有就空数组。
- relations：本章关系发生变化（甲、乙、从什么变成什么），没有就空数组。
- moves：本章人物位置发生变化（谁、去了哪、怎么去的/交代了什么），没有就空数组。
  只在正文明确写到移动或明确交代位置时记录；没动的人不要写。回忆里的移动不要当成现在的位置变化。
- characterStates：本章人物的生死去留发生变化（谁、变成什么状态、因为什么），没有就空数组。
  只在正文明确写到死亡、失踪、退场，或者「已经死了/走了的人又出现了」时记录；
  status 只能是 在场 / 死亡 / 失踪 / 退场。打斗很凶但没写死、只是怀疑他死了，都不算，不要推测。
  回忆章里过去的死亡要记，但 note 里写明是回忆里发生的事。
- items：本章关键物品的持有人或状态发生变化（物品、谁拿着、状态、怎么转手的），没有就空数组。
- factionStates：本章势力状态发生变化（势力、变成什么状态、因为什么），没有就空数组。
  只记正文明确写到的兴衰、结盟、翻脸、被打击；势力没变就不要写。
- placeStates：本章地点状态或占据发生变化（地点、状态、现在被谁占着、因为什么），没有就空数组。
- timeline：本章可上时间线的事件，按发生顺序；kind 只能是 event / foreshadow-plant / foreshadow-payoff；
  flashback 表示这件事发生在过去（回忆、旧事重提），不是本章的当下时间；
  revealChapter 是伏笔揭晓章号，只有 foreshadow-plant 且已知时才写数字，否则 null。

【输出格式】只输出 JSON，不要 Markdown、不要解释：
{{"summary":"120-200字本章摘要","characters":["出场人物"],"places":["地点"],
 "events":["按发生顺序的关键事件"],"storyTime":"故事内时间（可空）","isFlashback":false,
 "state":"章末状态",
 "knows":[{{"who":"人物","learned":"本章他知道了什么"}}],
 "relations":[{{"a":"甲","b":"乙","change":"从什么变成什么"}}],
 "moves":[{{"who":"人物","to":"地点","note":"怎么到的/交代了什么"}}],
 "characterStates":[{{"who":"人物","status":"在场|死亡|失踪|退场","note":"因为什么"}}],
 "items":[{{"name":"物品","holder":"谁拿着","state":"状态","note":"怎么转手的"}}],
 "factionStates":[{{"name":"势力","state":"变成什么状态","note":"因为什么"}}],
 "placeStates":[{{"name":"地点","state":"变成什么状态","occupied":"现在被谁占着","note":"因为什么"}}],
 "timeline":[{{"storyTime":"","place":"","characters":[],"event":"","kind":"event|foreshadow-plant|foreshadow-payoff","flashback":false,"revealChapter":null}}]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize_timeline(raw: Any, *, chapter: int, summary: str, story_time: str,
                        characters: list[str], at: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        event = _text(item.get("event"))
        if not event:
            continue
        kind = _text(item.get("kind"))
        if kind not in TIMELINE_KINDS:
            kind = "event"
        reveal = _num(item.get("revealChapter")) or None
        items.append({
            "chapter": chapter,
            "storyTime": _text(item.get("storyTime")) or story_time,
            "place": _text(item.get("place")),
            "characters": _str_list(item.get("characters")) or list(characters),
            "event": event,
            "kind": kind,
            "flashback": _flag(item.get("flashback")),
            "revealChapter": reveal,
            "source": "ai",
            "at": at,
        })
    if items:
        return items
    # 模型漏了 timeline：至少留一条事件，时间线不至于整章空白。
    return [{
        "chapter": chapter,
        "storyTime": story_time,
        "place": "",
        "characters": list(characters),
        "event": summary[:80],
        "kind": "event",
        "flashback": False,
        "revealChapter": None,
        "source": "ai",
        "at": at,
    }]


def generate_chapter_memory(
    root: str | os.PathLike,
    number: int,
    *,
    model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """读第 n 章正文提炼章记忆；已有记忆且 force=False 时跳过，不调模型。"""
    from .memory import clamp_summary

    chapter = _num(number)
    if chapter <= 0:
        raise ValueError("章号必须是正整数")

    existing = load_memory_rows(root)["byChapter"].get(chapter) or {}
    if existing.get("summary") and not force:
        return {"skipped": True, "chapter": chapter}

    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    bible = load_bible(root)
    entry = read_index_entry(root, chapter) or {}
    outline = _outline_row(root, chapter)
    title = _text(entry.get("title")) or _text((outline or {}).get("title")) or f"第{chapter}章"
    text = _chapter_text(root, chapter)
    prev = _prev_memory(root, chapter)

    used_model = model or _text(load_settings().get("fastModel"))
    result = chat(
        _chapter_messages(root, project, bible, chapter=chapter, title=title,
                          text=text, outline=outline, prev=prev),
        model=used_model or None, temperature=0.2, max_tokens=4000, timeout=240, reasoning="none",
    )
    raw = _parse_json(result.get("text"))
    if raw is None:
        snippet = str(result.get("text") or "")[:200]
        raise LLMError(f"第{chapter}章记忆没有返回可解析的 JSON。原文片段：{snippet}")

    summary = clamp_summary(raw.get("summary"), 400)
    if not summary:
        raise LLMError(f"第{chapter}章记忆的摘要为空；这次不写账（可以重试或换模型）")

    characters = _str_list(raw.get("characters"))
    places = _str_list(raw.get("places"))
    events = _str_list(raw.get("events"))
    story_time = _text(raw.get("storyTime"))
    is_flashback = _flag(raw.get("isFlashback"))
    end_state = _text(raw.get("state"))
    knows = _dict_list(raw.get("knows"), ("who", "learned"))
    relations = _dict_list(raw.get("relations"), ("a", "b", "change"))
    moves = _dict_list(raw.get("moves"), ("who", "to", "note"))
    character_states = _optional_rows(
        raw.get("characterStates"), ("who", "status", "note"), "who",
    )
    item_changes = _dict_list(raw.get("items"), ("name", "holder", "state", "note"))
    faction_changes = _optional_rows(raw.get("factionStates"), ("name", "state", "note"), "name")
    place_changes = _optional_rows(
        raw.get("placeStates"), ("name", "state", "occupied", "note"), "name",
    )
    at = _now()

    # 先算好时间线，再落盘：任何一步都不在「写了一半」的状态里。
    timeline = _normalize_timeline(raw.get("timeline"), chapter=chapter, summary=summary,
                                   story_time=story_time, characters=characters, at=at)

    from .memory import append_memory

    append_memory(root, {
        "kind": "chapter",
        "chapter": chapter,
        "title": title,
        "summary": summary,
        "characters": characters,
        "places": places,
        "events": events,
        "storyTime": story_time,
        "isFlashback": is_flashback,
        "state": end_state,
        "knows": knows,
        "relations": relations,
        "moves": moves,
        "characterStates": character_states,
        "items": item_changes,
        "factionStates": faction_changes,
        "placeStates": place_changes,
        "source": "ai",
        "model": str(result.get("model") or used_model),
    })
    for item in timeline:
        append_jsonl(project_path(root, TIMELINE_FILE), item)

    _record_usage(root, {
        "kind": "memory",
        "chapter": chapter,
        "tokens": int(result.get("usage", {}).get("total_tokens") or 0),
        "model": str(result.get("model") or used_model),
    })

    return {
        "chapter": chapter,
        "summary": summary,
        "characters": characters,
        "events": events,
        "isFlashback": is_flashback,
        "timelineCount": len(timeline),
    }


# --------------------------------------------------------------------------- #
# 卷记忆
# --------------------------------------------------------------------------- #


def _volume_messages(volume: dict[str, Any], digest: dict[str, Any]) -> list[dict[str, str]]:
    dims_block = "\n".join(f"- {key}：{hint}" for key, hint in VOLUME_DIM_HINTS.items())
    system = (
        "你是长篇网文的卷记忆编辑。你要把这一卷已经写好的章摘要压缩成「前面到底发生了什么」，"
        "供下一卷续写时直接使用。只依据给出的章摘要，不推测、不补设定。只输出一个 JSON 对象。"
    )
    user = f"""【本卷】{_text(volume.get('title'))}（第 {volume.get('from')}-{volume.get('to')} 章，已写 {digest.get('count') or 0} 章）

【本卷各章摘要】
{digest.get('text') or '（这一卷还没有正文）'}

【输出要求】
- summary：200-300 字，按时间顺序概括本卷主线：起点、核心冲突、关键转折、卷末状态。不要分点。
- dims：六个维度各 1-3 句，没有内容写空字符串：
{dims_block}

【输出格式】只输出 JSON，不要 Markdown、不要解释：
{{"summary":"200-300字卷摘要","dims":{{"mainline":"","threads":"","relations":"","knowledge":"","carryover":"","drift":""}}}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_volume_memory(
    root: str | os.PathLike,
    volume_index: int,
    *,
    model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """按卷生成 200-300 字总述 + 六维度；同范围已有卷记忆且 force=False 时跳过。"""
    from .memory import build_volume_digest, clamp_summary, load_volumes

    idx = _num(volume_index)
    volumes = load_volumes(root)
    if idx < 1 or idx > len(volumes):
        raise ValueError(f"卷号超出范围：第 {volume_index} 卷（共 {len(volumes)} 卷）")
    volume = volumes[idx - 1]
    vol_from, vol_to = _num(volume.get("from")), _num(volume.get("to"))

    existing = next(
        (m for m in load_memory_rows(root)["volumes"]
         if _num(m.get("from")) == vol_from and _num(m.get("to")) == vol_to),
        None,
    )
    if existing and not force:
        return {"skipped": True, "volume": idx, "from": vol_from, "to": vol_to}

    digest = build_volume_digest(root, chapter=vol_to)
    used_model = model or _text(load_settings().get("fastModel"))
    result = chat(
        _volume_messages(volume, digest),
        model=used_model or None, temperature=0.2, max_tokens=4000, timeout=240, reasoning="none",
    )
    raw = _parse_json(result.get("text"))
    if raw is None:
        snippet = str(result.get("text") or "")[:200]
        raise LLMError(f"第{idx}卷记忆没有返回可解析的 JSON。原文片段：{snippet}")
    summary = clamp_summary(raw.get("summary"), 400)
    if not summary:
        raise LLMError(f"第{idx}卷记忆的摘要为空；这次不写账（可以重试或换模型）")

    raw_dims = raw.get("dims") if isinstance(raw.get("dims"), dict) else raw
    dims = {key: _text(raw_dims.get(key)) for key in VOLUME_DIMS}

    from .memory import append_memory

    append_memory(root, {
        "kind": "volume",
        "volume": idx,
        "title": _text(volume.get("title")),
        "from": vol_from,
        "to": vol_to,
        "summary": summary,
        "dims": dims,
        "source": "ai",
        "model": str(result.get("model") or used_model),
    })
    _record_usage(root, {
        "kind": "memory-volume",
        "chapter": vol_to,
        "tokens": int(result.get("usage", {}).get("total_tokens") or 0),
        "model": str(result.get("model") or used_model),
    })

    return {
        "volume": idx,
        "title": _text(volume.get("title")),
        "from": vol_from,
        "to": vol_to,
        "summary": summary,
        "dims": dims,
    }


# --------------------------------------------------------------------------- #
# 正文落盘后自动回写
# --------------------------------------------------------------------------- #


def auto_write_back(
    root: str | os.PathLike,
    chapter: int,
    *,
    force: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """正文一落盘就回写记忆：本节记本章，本卷收尾时再补卷摘要。

    记忆是正文的派生数据，不该由作者手写；失败也不该让这一章失败——所以这里
    吞掉所有异常，只把原因带回给调用方（前端可以提示「记忆稍后补」）。
    """
    if os.environ.get("DSH_NOVEL_AUTO_MEMORY", "1").strip().lower() in ("0", "false", "off", "no"):
        return {"ok": False, "skipped": True, "reason": "自动回写已关闭（DSH_NOVEL_AUTO_MEMORY=0）"}
    out: dict[str, Any] = {"ok": False}
    try:
        out["chapter"] = generate_chapter_memory(root, chapter, model=model, force=force)
        out["ok"] = True
    except Exception as e:  # noqa: BLE001 — 记忆失败不影响正文
        out["error"] = str(e)
        return out

    try:
        from .memory import load_volumes

        for idx, volume in enumerate(load_volumes(root), 1):
            if _num(volume.get("to")) == _num(chapter):
                out["volume"] = generate_volume_memory(root, idx, model=model)
                break
    except Exception as e:  # noqa: BLE001 — 卷摘要失败下次补
        out["volumeError"] = str(e)
    return out


# --------------------------------------------------------------------------- #
# 退稿 / 恢复时撤回卷摘要
# --------------------------------------------------------------------------- #


def retract_volume_memory(root: str | os.PathLike, chapter: int) -> int:
    """退回某一章时，把覆盖它的卷摘要标为失效：旧摘要里可能写了这章的事。

    章记忆不删（按正文索引过滤即可），卷摘要跨章，只能追加一条 retracted 行盖掉。
    """
    from .memory import load_volumes

    n = _num(chapter)
    if n <= 0:
        return 0
    ranges = {
        (_num(v.get("from")), _num(v.get("to")))
        for v in load_volumes(root)
        if _num(v.get("from")) <= n <= _num(v.get("to"))
    }
    if not ranges:
        return 0
    out = 0
    with project_lock(root):
        rows = read_jsonl(project_path(root, MEMORY_FILE))
        live = {
            (_num(r.get("from")), _num(r.get("to")))
            for r in rows
            if isinstance(r, dict) and r.get("kind") == "volume" and not r.get("retracted")
        }
        for frm, to in sorted(ranges):
            if (frm, to) not in live:
                continue
            append_jsonl(project_path(root, MEMORY_FILE), {
                "kind": "volume", "from": frm, "to": to,
                "retracted": True, "reason": f"第{n}章退回", "at": _now(),
            })
            out += 1
    return out


def restore_volume_memory(root: str | os.PathLike, chapter: int) -> int:
    """废章恢复后，把退稿时盖掉的卷摘要恢复回来（重新追加原摘要，追加式账本）。"""
    from .memory import load_volumes

    n = _num(chapter)
    if n <= 0:
        return 0
    ranges = {
        (_num(v.get("from")), _num(v.get("to")))
        for v in load_volumes(root)
        if _num(v.get("from")) <= n <= _num(v.get("to"))
    }
    if not ranges:
        return 0
    out = 0
    with project_lock(root):
        rows = read_jsonl(project_path(root, MEMORY_FILE))
        latest: dict[tuple[int, int], dict[str, Any]] = {}
        original: dict[tuple[int, int], dict[str, Any]] = {}
        for r in rows:
            if not isinstance(r, dict) or r.get("kind") != "volume":
                continue
            key = (_num(r.get("from")), _num(r.get("to")))
            if key not in ranges:
                continue
            latest[key] = r
            if not r.get("retracted"):
                original[key] = r
        for key, row in latest.items():
            if not row.get("retracted"):
                continue
            src = original.get(key)
            if not src:
                continue
            append_jsonl(project_path(root, MEMORY_FILE), {**src, "retracted": False, "at": _now()})
            out += 1
    return out


# --------------------------------------------------------------------------- #
# 批量补齐
# --------------------------------------------------------------------------- #


def generate_memory_batch(
    root: str | os.PathLike,
    frm: int,
    to: int,
    *,
    model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """按章号升序逐章生成；单章失败只记账，不中断后面的章。"""
    start, stop = _num(frm), _num(to)
    if start <= 0 or stop <= 0 or stop < start:
        raise ValueError(f"章号范围不对：{frm}–{to}")
    numbers = sorted({
        _num(c.get("number")) for c in read_index(root)
        if start <= _num(c.get("number")) <= stop and _num(c.get("chars")) > 0
    })
    failed: list[dict[str, Any]] = []
    ok = 0
    timeline_count = 0
    for chapter in numbers:
        try:
            res = generate_chapter_memory(root, chapter, model=model, force=force)
            ok += 1
            timeline_count += int(res.get("timelineCount") or 0)
        except Exception as e:  # noqa: BLE001 — 单章失败不影响整批
            failed.append({"chapter": chapter, "error": str(e)})
    return {
        "total": len(numbers),
        "ok": ok,
        "failed": failed,
        "timelineCount": timeline_count,
    }


# --------------------------------------------------------------------------- #
# 记忆总览（GET /memory，只读、不调模型）
# --------------------------------------------------------------------------- #


def _same_range(memory: dict[str, Any], volume: dict[str, Any]) -> bool:
    return (_num(memory.get("from")), _num(memory.get("to"))) == (
        _num(volume.get("from")), _num(volume.get("to")),
    )


def _timeline_rows(root: str | os.PathLike) -> list[dict[str, Any]]:
    """时间线是事件级账：同章可能有多条，所以不能按 chapter 折叠掉。

    force 重生成会为同章再追加一批；只保留该章 at 最新的一批，避免旧事件重复出现。
    只返回正文索引里还在的章：退稿章的旧事件不该继续出现在时间线上，恢复后自动回来。
    """
    live = {_num(c.get("number")) for c in read_index(root) if _num(c.get("number")) > 0}
    rows = [r for r in read_jsonl(project_path(root, TIMELINE_FILE))
            if isinstance(r, dict) and not r.get("__corrupt") and _num(r.get("chapter")) in live]
    by_chapter: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_chapter.setdefault(_num(row.get("chapter")), []).append(row)
    out: list[dict[str, Any]] = []
    for chapter in sorted(by_chapter):
        items = by_chapter[chapter]
        stamps = [str(r.get("at") or "") for r in items if r.get("at")]
        if stamps:
            latest = max(stamps)
            items = [r for r in items if str(r.get("at") or "") == latest]
        out.extend(items)
    return out


def _relation_edges(by_chapter: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for chapter in sorted(by_chapter):
        row = by_chapter[chapter]
        for item in row.get("relations") or []:
            if not isinstance(item, dict):
                continue
            a, b, change = _text(item.get("a")), _text(item.get("b")), _text(item.get("change"))
            if not (a and b and change):
                continue
            key = tuple(sorted((a, b)))
            if _num((edges.get(key) or {}).get("chapter")) > chapter:
                continue
            edges[key] = {"a": a, "b": b, "state": change, "chapter": chapter}
    return sorted(edges.values(), key=lambda e: e["chapter"])


def _touches(row: dict[str, Any], name: str) -> bool:
    if name in (row.get("characters") or []):
        return True
    for item in row.get("knows") or []:
        who = _text((item or {}).get("who"))
        if who and (who == name or name in who or who in name):
            return True
    for item in row.get("relations") or []:
        for who in (_text((item or {}).get("a")), _text((item or {}).get("b"))):
            if who and (who == name or name in who or who in name):
                return True
    return False


def _character_states(
    root: str | os.PathLike,
    bible: dict[str, Any],
    by_chapter: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    from .memory import character_state

    names = [_text(c.get("name")) for c in (bible.get("characters") or []) if _text(c.get("name"))]
    if not names:
        for chapter in sorted(by_chapter):
            for name in by_chapter[chapter].get("characters") or []:
                name = _text(name)
                if name and name not in names:
                    names.append(name)
    if not names or not by_chapter:
        return []

    last_chapter = max(by_chapter)
    out: list[dict[str, Any]] = []
    for name in names[:20]:
        # character_state 只算「< chapter」的章记忆；传末章 +1 才包含最新一章。
        state = character_state(root, chapter=last_chapter + 1, names=[name])
        text = _text(state.get("text"))
        if not text:
            continue
        touched = [n for n in sorted(by_chapter) if _touches(by_chapter[n], name)]
        out.append({"name": name, "state": text, "chapter": touched[-1] if touched else 0})
    return out


def memory_overview(root: str | os.PathLike) -> dict[str, Any]:
    """记忆页的整包数据：覆盖度 + 章记忆 + 卷记忆 + 时间线 + 关系 + 人物状态。"""
    from .memory import load_memory_rows, load_volumes

    project = load_project(root) or {}
    index = read_index(root)
    rows = load_memory_rows(root)
    by_chapter = rows["byChapter"]
    volume_rows = rows["volumes"]
    volumes = load_volumes(root)

    written = sorted({_num(c.get("number")) for c in index if _num(c.get("chars")) > 0})
    written_set = set(written)
    missing = [n for n in written if not _text((by_chapter.get(n) or {}).get("summary"))]

    chapters = []
    for entry in sorted(index, key=lambda c: _num(c.get("number"))):
        number = _num(entry.get("number"))
        if number not in written_set:
            continue
        memory = by_chapter.get(number) or {}
        chapters.append({
            "chapter": number,
            "title": _text(entry.get("title")) or _text(memory.get("title")),
            "summary": _text(memory.get("summary")),
            "characters": list(memory.get("characters") or entry.get("characters") or []),
            "events": list(memory.get("events") or []),
            "storyTime": _text(memory.get("storyTime")),
            "isFlashback": _flag(memory.get("isFlashback")),
            "at": _text(memory.get("at")),
        })

    # 卷列表以结构卷为准：还没生成卷摘要的卷也要出现，前端才能发起首次生成。
    volume_items = []
    used: set[int] = set()
    for idx, volume in enumerate(volumes, 1):
        memory = next((m for m in volume_rows if _same_range(m, volume)), None)
        if memory is not None:
            used.add(id(memory))
        volume_items.append({
            "volume": idx,
            "title": _text((memory or {}).get("title")) or _text(volume.get("title")),
            "from": _num(volume.get("from")),
            "to": _num(volume.get("to")),
            "summary": _text((memory or {}).get("summary")),
            "dims": (memory or {}).get("dims") if isinstance((memory or {}).get("dims"), dict) else {},
        })
    for memory in sorted(volume_rows, key=lambda r: _num(r.get("from"))):
        if id(memory) in used:
            continue
        volume_items.append({
            "volume": _num(memory.get("volume")),
            "title": _text(memory.get("title")),
            "from": _num(memory.get("from")),
            "to": _num(memory.get("to")),
            "summary": _text(memory.get("summary")),
            "dims": memory.get("dims") if isinstance(memory.get("dims"), dict) else {},
        })

    timeline = []
    for row in _timeline_rows(root):
        event = _text(row.get("event")) or _text(row.get("summary"))
        if not event:
            events = row.get("events") if isinstance(row.get("events"), list) else []
            event = _text(events[0]) if events else ""
        kind = _text(row.get("kind"))
        timeline.append({
            "chapter": _num(row.get("chapter")),
            "storyTime": _text(row.get("storyTime")) or _text(row.get("inWorldTime")),
            "place": _text(row.get("place")) or "、".join(_str_list(row.get("places") or row.get("locations"))),
            "characters": _str_list(row.get("characters")),
            "event": event,
            "kind": kind if kind in TIMELINE_KINDS else "event",
            "flashback": _flag(row.get("flashback")),
            "revealChapter": _num(row.get("revealChapter")) or None,
        })

    return {
        "coverage": {
            "chaptersWithText": len(written),
            "chaptersWithMemory": sum(1 for n in written if _text((by_chapter.get(n) or {}).get("summary"))),
            "volumes": len(volumes),
            "volumesWithMemory": sum(1 for v in volumes if any(_same_range(m, v) for m in volume_rows)),
            "missing": missing,
        },
        "chapters": chapters,
        "volumes": volume_items,
        "timeline": timeline,
        "relations": _relation_edges(by_chapter),
        "characters": _character_states(root, load_bible(root), by_chapter),
    }
