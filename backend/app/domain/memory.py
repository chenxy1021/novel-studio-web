"""写作记忆层：决定「写第 N 章时到底把哪些前情装进上下文包」。

移植自 novel-studio/lib/memory.js。

L0 状态账（人物现状 / 关系 / 已知真相 / 开放线）
L1 卷级记忆（按大纲卷分组的「这部/卷发生了什么」）
L2 章级记忆（关键事件 + 结束时状态，近章给全文，远章给一句话）
L3 原文（只在点名回查时翻）
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..store import append_jsonl, read_json, read_jsonl, read_text, write_json
from ..store.paths import LAYOUT, project_path

MEMORY_FILE = "ledger/memory.jsonl"
VOLUMES_FILE = "ledger/volumes.json"
RELATIONS_FILE = "ledger/relations.json"

STRONG_RECENT = 8     # 最近 8 章给完整摘要 + 事件
FAR_LINES = 80        # 再往前 80 章，一章一句（更早的落到卷摘要 + 关键词回查）
DEFAULT_BUDGET = 12000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _num(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _read_index(root: str | os.PathLike) -> list[dict[str, Any]]:
    """chapters/index.json 是 JSON 数组（不是 jsonl）；读错会让章记忆/卷盘点一直「没有正文」。"""
    v = read_json(project_path(root, LAYOUT["chapter_index"]), [])
    return v if isinstance(v, list) else []


# ------------------------------- 卷索引 -------------------------------

_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_num(s: Any) -> int | None:
    if not s:
        return None
    s = str(s)
    if re.fullmatch(r"\d+", s):
        return int(s)
    n = cur = 0
    for ch in s:
        if ch in _CN:
            cur = _CN[ch]
        elif ch == "百":
            n += (cur or 1) * 100
            cur = 0
        elif ch == "千":
            n += (cur or 1) * 1000
            cur = 0
    return n + cur or None


_RANGES = re.compile(r"第\s*([0-9一二三四五六七八九十百千]+)\s*章?\s*[~～\-—–至到]\s*第?\s*([0-9一二三四五六七八九十百千]+)\s*章")
# 卷头行：「第一部：旧卷疑云（第 1-120 章）」「第2卷 轮回之证」「## 第一卷 风起」
_VOL_HEAD = re.compile(r"^#{0,6}\s*(第\s*([0-9一二三四五六七八九十百千]+)\s*[部卷篇]|[部卷篇]\s*[一二三四五六七八九十0-9]+)\s*[：:、.·\s]*(.*)$")
_OVERVIEW = re.compile(r"^(全书|主线|总览|素材|开篇|结局层)")


def _span(text: str) -> list[dict[str, int]]:
    res = []
    for m in _RANGES.finditer(text):
        f, t = cn_num(m.group(1)), cn_num(m.group(2))
        if f and t and t >= f:
            res.append({"from": f, "to": t})
    return res


def parse_volumes(outline_text: Any) -> list[dict[str, Any]]:
    """从大纲 Markdown 里抠卷索引：[{title, from, to}]。"""
    lines = str(outline_text or "").replace("\r\n", "\n").split("\n")
    vols: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_overview = False
    for raw in lines:
        # 卷头常写成列表项 / 加粗：`- **第一卷 第 1-36 章｜第一单**`
        line = re.sub(r"\*+", "", re.sub(r"^[*>\-+\s]+", "", raw.strip())).strip()
        head = re.match(r"^#{2,6}\s*(.+)$", line)
        vol_head = _VOL_HEAD.match(line)
        if head or vol_head:
            t = (head.group(1).strip() if head else vol_head.group(3).strip())
            if _OVERVIEW.match(t):
                in_overview = True
            if vol_head:
                in_overview = False
                raw_name = re.sub(r"[（(].*$", "", t or "")
                raw_name = re.sub(r"^(第\s*[0-9一二三四五六七八九十百千]+\s*[部卷篇]|[部卷篇]\s*[一二三四五六七八九十0-9]+)", "", raw_name)
                raw_name = re.sub(r"^第\s*[0-9一二三四五六七八九十百千]+\s*[-–—~～至到]\s*[0-9一二三四五六七八九十百千]+\s*章", "", raw_name)
                raw_name = re.sub(r"^[：:、.·｜|\s]+", "", raw_name).strip()
                # 只认短的卷名；「卷一 第 1-30 章：任务——……」后面是描述，不能当卷名
                label = re.split(r"[：:｜|（(]", raw_name)[0].strip()
                name = label if (label and len(label) <= 12 and not re.match(r"^(任务|矛盾|新增|情绪|大致|回收|新埋|节奏)", label)) else ""
                head_label = re.sub(r"(第)\s+(?=[0-9一二三四五六七八九十百千])", r"\1", vol_head.group(1))
                cur = {
                    "title": (head_label + (" " + name if name else "")).strip()[:60],
                    "from": 0, "to": 0, "src": [],
                    # 「部」只是分组：下面还有「卷」时以卷为准
                    "part": "部" in vol_head.group(1),
                }
                vols.append(cur)
            marks = _span(re.sub(r"^#{2,6}", "", line))
            if cur is not None and not in_overview:
                cur["src"].extend(marks)
            continue
        if cur is not None and not in_overview:
            cur["src"].extend(_span(line))

    out: list[dict[str, Any]] = []
    for v in vols:
        if not v["src"]:
            continue
        out.append({
            "title": v["title"],
            "from": min(x["from"] for x in v["src"]),
            "to": max(x["to"] for x in v["src"]),
            "part": bool(v["part"]),
        })

    def covered(part: dict[str, Any]) -> bool:
        kids = sorted(
            [c for c in out if not c["part"] and part["from"] <= c["from"] and c["to"] <= part["to"]],
            key=lambda c: c["from"],
        )
        at = part["from"]
        for k in kids:
            if k["from"] > at:
                return False
            at = max(at, k["to"] + 1)
            if at > part["to"]:
                return True
        return at > part["to"]

    kept = [v for v in out if not v["part"] or not covered(v)]
    # 大纲完全没写卷头：退回按章节区间拆
    if not out:
        section, overview = "", False
        for raw in lines:
            line = raw.strip()
            head = re.match(r"^#{2,6}\s*(.+)$", line)
            if head:
                section = head.group(1).strip()
                overview = bool(_OVERVIEW.match(section))
                continue
            if overview:
                continue
            for m in _span(line):
                out.append({"title": (section or f"第{m['from']}-{m['to']}章")[:60], "from": m["from"], "to": m["to"]})

    seen: set[str] = set()
    uniq = []
    for v in kept:
        k = f"{v['from']}-{v['to']}"
        if k in seen:
            continue
        seen.add(k)
        uniq.append(v)
    uniq.sort(key=lambda v: (v["from"], v["to"]))
    return [{"title": v["title"], "from": v["from"], "to": v["to"]} for v in uniq]


def load_volumes(root: str | os.PathLike) -> list[dict[str, Any]]:
    rows = [r for r in read_jsonl(project_path(root, VOLUMES_FILE)) if not r.get("__corrupt")]
    if not rows:
        return []
    last = rows[-1]
    return last.get("volumes") if isinstance(last.get("volumes"), list) else []


def save_volumes(root: str | os.PathLike, outlines: Any, outline_text: Any) -> list[dict[str, Any]]:
    from_outline = parse_volumes(outline_text)
    marks: list[dict[str, Any]] = []
    for o in outlines or []:
        vol = (o or {}).get("volume") if isinstance(o, dict) else None
        if isinstance(vol, dict):
            marks.append({"to": _num(vol.get("to")), "title": str(vol.get("title") or vol.get("name") or "")})
    marks = sorted((m for m in marks if m["to"] > 0), key=lambda m: m["to"])
    manual: list[dict[str, Any]] = []
    prev_to = 0
    for m in marks:
        if m["to"] <= prev_to:
            continue
        if any(v["from"] <= m["to"] <= v["to"] for v in from_outline):
            prev_to = m["to"]
            continue
        manual.append({"title": m["title"] or f"第{prev_to + 1}-{m['to']}章", "from": prev_to + 1, "to": m["to"]})
        prev_to = m["to"]

    merged = list(from_outline)
    for m in manual:
        # 与已有区间重叠的丢掉（大纲里的更权威）
        if any(not (m["to"] < v["from"] or m["from"] > v["to"]) for v in merged):
            continue
        merged.append(m)
    if not merged:
        return []
    merged.sort(key=lambda v: v["from"])
    # 卷索引没变就不重复追加：面板每次刷新都会重算
    prev = read_jsonl(project_path(root, VOLUMES_FILE))
    if prev and prev[-1].get("volumes") == merged:
        return merged
    append_jsonl(project_path(root, VOLUMES_FILE), {
        "volumes": merged, "source": "outline+chapters" if manual else "outline", "at": _now(),
    })
    return merged


def refresh_volumes(root: str | os.PathLike, load_outlines: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    """大纲文本变了就刷新卷索引（保存大纲 / 生成大纲 / 写细纲三处都调）。"""
    proj = read_json(project_path(root, LAYOUT["project"]), None)
    if not proj:
        return []
    try:
        outlines = (load_outlines() if load_outlines else []) or []
    except Exception:  # noqa: BLE001 — 老代码同样吞掉，卷索引失败不该挡住主流程
        outlines = []
    vols = save_volumes(root, outlines, proj.get("outlineText") or "")
    if not proj.get("volumeCount") and vols:
        proj["volumeCount"] = len(vols)
        proj["updatedAt"] = _now()
        write_json(project_path(root, LAYOUT["project"]), proj)
    return vols


def volume_of(volumes: list[dict[str, Any]] | None, n: Any) -> dict[str, Any] | None:
    k = _num(n)
    return next((v for v in (volumes or []) if int(v["from"]) <= k <= int(v["to"])), None)


def group_by_volume(volumes: list[dict[str, Any]], numbers: list[int]) -> list[dict[str, Any]]:
    if not volumes:
        return []
    out = []
    for v in volumes:
        nums = sorted(n for n in numbers if int(v["from"]) <= n <= int(v["to"]))
        if nums:
            out.append({"volume": v, "numbers": nums})
    return out


# ------------------------------- 设定别名 -------------------------------

def aliases_of(c: dict[str, Any] | None) -> list[str]:
    """人物的所有称呼：name + aliases（数组或「小默、默哥」这种字符串都认）。"""
    raw = (c or {}).get("aliases")
    if isinstance(raw, list):
        lst = raw
    elif isinstance(raw, str):
        lst = re.split(r"[、,，/\s]+", raw)
    else:
        lst = []
    seen: list[str] = []
    for s in [(c or {}).get("name"), *lst]:
        t = str(s or "").strip()
        if t and t not in seen:
            seen.append(t)
    return seen


def resolve_character(bible: dict[str, Any] | None, name: Any) -> dict[str, Any] | None:
    """名字 → 角色；正文里用别名也算同一个人。设定里没写的返回 None。"""
    want = str(name or "").strip()
    if not want:
        return None
    chars = (bible or {}).get("characters") or []
    return (
        next((c for c in chars if c.get("name") == want), None)
        or next((c for c in chars if want in aliases_of(c)), None)
        or next((c for c in chars if any(len(a) >= 2 and (a in want or want in a) for a in aliases_of(c))), None)
    )


def characters_mentioned(bible: dict[str, Any] | None, text: Any) -> list[str]:
    """正文里出现的人物（含别名），返回设定里的规范名（按出场顺序、去重）。"""
    t = str(text or "")
    return [c["name"] for c in ((bible or {}).get("characters") or [])
            if c.get("name") and any(a in t for a in aliases_of(c))]


# ------------------------------- 摘要 -------------------------------

SUMMARY_MAX = 400
SUMMARY_TARGET = 160


def _char_len(s: Any) -> int:
    return len(re.sub(r"\s+", "", str(s or "")))


def clamp_summary(text: Any, max_len: int = SUMMARY_MAX) -> str:
    """摘要成形：多行压成一句一段，超长就丢掉最后一句、补省略号。"""
    s = re.sub(r"\s*\n+\s*", " ", str(text or "")).strip()
    if _char_len(s) <= max_len:
        return s
    head = s[: max(1, math.floor(max_len * 0.95))]
    cut = max(head.rfind("。"), head.rfind("；"), head.rfind("！"), head.rfind("？"))
    return (head[: cut + 1] if cut > max_len * 0.4 else head) + "…"


def load_memory_rows(root: str | os.PathLike) -> dict[str, Any]:
    """读章记忆与卷记忆。

    章记忆按「正文索引」过滤：退稿后章已不在 chapters/index.json，它的记忆就不该
    再进前情 / 关系 / 人物状态；从废章恢复时章号回到索引，记忆自动重新生效，不用
    另记一条撤回事件。卷记忆按区间折叠，``retracted`` 的行会盖掉同区间旧摘要。
    """
    from ..store import read_index

    rows = read_jsonl(project_path(root, MEMORY_FILE))
    live = {
        _num(c.get("number"))
        for c in read_index(root)
        if _num(c.get("number")) > 0
    }
    by_chapter: dict[int, dict[str, Any]] = {}
    volume_by_range: dict[tuple[int, int], dict[str, Any]] = {}
    for r in rows:
        if not r or r.get("__corrupt"):
            continue
        if r.get("kind") == "volume":
            volume_by_range[(_num(r.get("from")), _num(r.get("to")))] = r
            continue
        if r.get("kind") == "character-state":
            continue
        if r.get("chapter") is not None:
            chapter = _num(r.get("chapter"))
            if chapter in live:
                # 同章重写后取最新；老版本落的摘要行没有 kind，不能盖掉带关系/位移的章记忆。
                prev = by_chapter.get(chapter) or {}
                if r.get("kind") == "chapter" or prev.get("kind") != "chapter":
                    by_chapter[chapter] = r
            else:
                by_chapter.pop(chapter, None)
    volumes = [r for r in volume_by_range.values() if not r.get("retracted")]
    volumes.sort(key=lambda r: _num(r.get("to")))
    return {"byChapter": by_chapter, "volumes": volumes, "rows": rows}


def append_memory(root: str | os.PathLike, row: dict[str, Any]) -> None:
    append_jsonl(project_path(root, MEMORY_FILE), {**row, "at": _now()})


# ------------------------------- 章级记忆（L2） -------------------------------

def build_echo_memory(root: str | os.PathLike, *, chapter: Any, budget_chars: int = DEFAULT_BUDGET,
                      focus: list[str] | None = None) -> dict[str, Any]:
    n = _num(chapter)
    if not n:
        return {"text": "", "chars": 0, "covered": 0}
    index = [c for c in _read_index(root) if isinstance(c.get("number"), (int, float))]
    before = sorted((c for c in index if _num(c["number"]) < n), key=lambda c: _num(c["number"]))
    if not before:
        return {"text": "", "chars": 0, "covered": 0}
    by_chapter = load_memory_rows(root)["byChapter"]
    strong_from = max(1, n - STRONG_RECENT)
    far_start = max(1, strong_from - FAR_LINES)
    focus_set = {str(f) for f in (focus or [])}

    def hit_focus(c: dict[str, Any]) -> bool:
        return bool(focus_set) and any(any(f in str(x) or str(x) in f for f in focus_set) for x in (c.get("characters") or []))

    near = [c for c in before if _num(c["number"]) >= strong_from or hit_focus(c)]
    far = [c for c in before if _num(c["number"]) < strong_from and not hit_focus(c)]
    clipped = [c for c in far if _num(c["number"]) < far_start]
    lines: list[str] = []
    if clipped:
        lines.append(
            f"更早的第 {_num(before[0]['number'])}-{_num(clipped[-1]['number'])} 章（共 {len(clipped)} 章）已滑出近章记忆，"
            "只剩卷摘要与时间线里的记录。需要原话或细节时，到「记忆」页用关键词回查（确定性命中，带章号出处）。"
        )
    far_in = [c for c in far if _num(c["number"]) >= far_start]
    if far_in:
        lines.append(f"### 前情一句一章（第 {_num(far_in[0]['number'])}-{_num(far_in[-1]['number'])} 章）")
        for c in far_in:
            raw = (c.get("summary") or (by_chapter.get(_num(c["number"])) or {}).get("summary") or "")
            one = clamp_summary(re.split(r"[。！？\n]", str(raw))[0] if raw else "", 80)
            lines.append(f"- 第{_num(c['number'])}章《{c.get('title') or ''}》：{one or '（无摘要）'}")

    def trim() -> bool:
        """放不下时先丢远章那句摘要、再丢 near 最旧章的整块；删无可删返回 False，避免死循环。"""
        at = next((i for i, line in enumerate(lines) if line.startswith("### 前情一句一章")), -1)
        if at >= 0:
            end = next((i for i, line in enumerate(lines) if i > at and line.startswith("### ")), -1)
            stop = end if end > 0 else len(lines)
            if stop - at > 1:
                lines.pop(stop - 1)
                return True
            del lines[at:stop]
            return True
        near_head = next((i for i, line in enumerate(lines) if line.startswith("### 最近几章")), -1)
        if near_head >= 0:
            starts = []
            for i in range(near_head + 1, len(lines)):
                if lines[i].startswith("### "):
                    break
                if re.match(r"^- 第\s*\d+\s*章", lines[i]):
                    starts.append(i)
            if len(starts) > 1:
                del lines[starts[0]:starts[1]]
                return True
        return False

    if near:
        lines.append("### 最近几章（写新章必须接上）")
        for c in near:
            num = _num(c["number"])
            m = by_chapter.get(num) or {}
            chars = "、".join(c.get("characters") or m.get("characters") or [])
            lines.append(
                f"- 第{num}章《{c.get('title') or ''}》{f'｜出场：{chars}' if chars else ''}"
                f"{' · 与本章相关，单独调出' if hit_focus(c) else ''}"
            )
            summary = clamp_summary(m.get("summary") or c.get("summary") or "", 240)
            if summary:
                lines.append(f"  摘要：{summary}")
            if m.get("events"):
                lines.append(f"  关键事件：{'；'.join(str(x) for x in m['events'][:8])}")
            if m.get("state"):
                lines.append(f"  结束时：{clamp_summary(m['state'], 200)}")
            # 硬上限兜底：最多修剪 lines.length 次，防止极端数据下空转
            guard = len(lines) + 4
            while len("\n".join(lines)) > budget_chars and guard > 0:
                guard -= 1
                if not trim():
                    break
    text = "\n".join(lines)
    return {"text": text, "chars": len(text), "covered": len(before)}


# ------------------------------- 卷级记忆（L1） -------------------------------

def volume_memory(root: str | os.PathLike, *, chapter: Any, volumes: list[dict[str, Any]] | None = None,
                  budget_chars: int = 1200) -> dict[str, Any]:
    n = _num(chapter)
    vs = volumes if volumes else load_volumes(root)
    cur = volume_of(vs, n)
    if not cur:
        return {"text": "", "chars": 0, "volume": None}
    mem = load_memory_rows(root)["volumes"]
    lines = []
    # 不假设 vs 已按 to 升序且不重叠：显式排序，避免中途 break 漏掉更早的卷
    prior = sorted((v for v in vs if _num(v.get("to")) < _num(cur["from"])), key=lambda v: _num(v.get("to")))
    for v in prior:
        m = next((x for x in mem if _num(x.get("to")) == _num(v.get("to"))), None)
        lines.append(
            f"- {v['title']}（第{v['from']}-{v['to']}章）"
            + (f"：{clamp_summary(m['summary'], 220)}" if m and m.get("summary") else "（还没做卷记忆）")
        )
    if not lines:
        return {"text": "", "chars": 0, "volume": cur}
    text = "前面各卷发生了什么（不要在新章里重新交代）：\n" + "\n".join(lines)
    if len(text) > budget_chars:
        text = text[:budget_chars] + "…"
    return {"text": text, "chars": len(text), "volume": cur}


# ------------------------------- 卷底稿 -------------------------------

def build_volume_digest(root: str | os.PathLike, *, chapter: Any) -> dict[str, Any]:
    n = _num(chapter)
    if not n:
        raise ValueError("需要 chapter（盘点哪一章所在的卷）")
    v = volume_of(load_volumes(root), n)
    if not v:
        raise ValueError(
            f"第{n}章落在任何已识别的大纲卷之外。先把大纲里的卷写成「第 a-b 章」的区间，或在细纲写入 volume.chapters"
        )
    to = min(_num(v["to"]), n)
    index = sorted((c for c in _read_index(root) if _num(v["from"]) <= _num(c.get("number")) <= to),
                   key=lambda c: _num(c["number"]))
    by_chapter = load_memory_rows(root)["byChapter"]
    rows = [
        f"第{_num(c['number'])}章《{c.get('title') or ''}》："
        f"{clamp_summary((by_chapter.get(_num(c['number'])) or {}).get('summary') or c.get('summary') or c.get('title') or '', 160)}"
        for c in index
    ]
    return {
        "volume": v, "from": v["from"], "to": to, "count": len(rows),
        "text": "\n".join(rows) if rows else "（这一卷还没有正文）",
        "dims": {
            "mainline": "主线推进到哪一步（对比大纲本卷任务）",
            "threads": "哪些支线/人物线被推进或丢下",
            "relations": "关系变化（谁和谁从什么变成什么）",
            "knowledge": "读者目前知道的真相 / 主角不知道的部分",
            "carryover": "必须带进下一卷的未收线索",
            "drift": "与大纲本卷任务不一致的地方",
        },
    }


# ------------------------------- 人物状态（L0） -------------------------------

def character_state(root: str | os.PathLike, *, chapter: Any, names: list[str] | None = None) -> dict[str, Any]:
    """「截至第 n 章，这个人知道什么、和谁是什么关系」。"""
    n = _num(chapter)
    want = [str(x) for x in (names or []) if x]
    if not n or not want:
        return {"text": "", "touches": {}}
    by_chapter = load_memory_rows(root)["byChapter"]
    rows = sorted((r for r in by_chapter.values() if _num(r.get("chapter")) < n), key=lambda r: _num(r.get("chapter")))
    knows: dict[str, list[dict[str, Any]]] = {}
    rel: dict[str, dict[str, dict[str, Any]]] = {}
    touches = {w: 0 for w in want}
    for r in rows:
        for k in r.get("knows") or []:
            if not isinstance(k, dict) or not k.get("who") or not k.get("learned"):
                continue
            hit = next((w for w in want if str(k["who"]) in w or w in str(k["who"])), None)
            if not hit:
                continue
            knows.setdefault(hit, []).append({"chapter": _num(r.get("chapter")), "learned": k["learned"]})
            touches[hit] += 1
        for x in r.get("relations") or []:
            if not isinstance(x, dict) or not x.get("a") or not x.get("b") or not x.get("change"):
                continue
            for who in (x["a"], x["b"]):
                if who not in want:
                    continue
                other = x["b"] if who == x["a"] else x["a"]
                rel.setdefault(who, {})[other] = {"change": x["change"], "chapter": _num(r.get("chapter"))}
                touches[who] += 1
    lines = []
    for who in want:
        ks = [f"第{k['chapter']}章知道：{clamp_summary(k['learned'], 90)}" for k in (knows.get(who) or [])[-4:]]
        rs = [f"与{o}：{clamp_summary(v['change'], 90)}（第{v['chapter']}章）" for o, v in list((rel.get(who) or {}).items())[-4:]]
        if not ks and not rs:
            continue
        lines.append(f"- {who}\n" + "\n".join(f"  · {x}" for x in [*ks, *rs]))
    return {"text": "\n".join(lines), "touches": touches}


# ------------------------------- 人物关系表 -------------------------------

def load_relations(root: str | os.PathLike) -> list[dict[str, Any]]:
    v = read_json(project_path(root, RELATIONS_FILE), {"edges": []})
    return v["edges"] if isinstance(v, dict) and isinstance(v.get("edges"), list) else []


def update_relations(root: str | os.PathLike, frm: int = 1, to: float = math.inf) -> list[dict[str, Any]]:
    """从章记忆的 relations 汇总成一张边表；同一对人以最新章为准。"""
    by_chapter = load_memory_rows(root)["byChapter"]
    rows = sorted((r for r in by_chapter.values() if frm <= _num(r.get("chapter")) <= to), key=lambda r: _num(r.get("chapter")))
    if not rows:
        return []
    edges = {tuple(sorted((e["a"], e["b"]))): e for e in load_relations(root)}
    for r in rows:
        for x in r.get("relations") or []:
            if not isinstance(x, dict) or not x.get("a") or not x.get("b") or not x.get("change"):
                continue
            k = tuple(sorted((x["a"], x["b"])))
            if _num((edges.get(k) or {}).get("chapter")) > _num(r.get("chapter")):
                continue
            edges[k] = {"a": x["a"], "b": x["b"], "state": x["change"], "chapter": _num(r.get("chapter"))}
    out = sorted(edges.values(), key=lambda e: e["chapter"])
    write_json(project_path(root, RELATIONS_FILE), {"edges": out})
    return out


def effective_relations(
    root: str | os.PathLike,
    bible: dict[str, Any],
    *,
    before_chapter: float = math.inf,
) -> list[dict[str, Any]]:
    """底稿 + 章记忆的关系变化，同一对只留一条，状态取最新章。

    只在读的时候合，不写进 bible：退稿后章记忆不再进表，关系自然回退。
    正反两种写法（甲→乙 / 乙→甲）算同一对。
    """
    rows: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}

    def add(row: dict[str, Any], chapter: int) -> None:
        a, b = str(row.get("a") or "").strip(), str(row.get("b") or "").strip()
        state = str(row.get("state") or row.get("change") or "").strip()
        if not a or not b or a == b or not state:
            return
        key = tuple(sorted((a, b)))
        hit = index.get(key)
        if hit is None:
            hit = {"a": a, "b": b, "state": state,
                   "note": str(row.get("note") or "").strip(), "chapter": chapter}
            index[key] = hit
            rows.append(hit)
            return
        if chapter >= _num(hit.get("chapter")):
            hit["state"], hit["chapter"] = state, chapter
        note = str(row.get("note") or "").strip()
        if len(note) > len(hit.get("note") or ""):
            hit["note"] = note

    for e in bible.get("relations") or []:
        if isinstance(e, dict):
            add(e, _num(e.get("chapter")))
    by_chapter = load_memory_rows(root)["byChapter"]
    for ch in sorted(by_chapter):
        if ch >= before_chapter:
            break
        for x in by_chapter[ch].get("relations") or []:
            if isinstance(x, dict):
                add(x, ch)
    return rows


def relation_lines(root: str | os.PathLike, names: list[str] | None = None) -> str:
    """上下文包用：和本章出场人物有关的现有关系（最多 20 条）。"""
    if not names:
        return ""
    hit = [e for e in load_relations(root) if e.get("a") in names or e.get("b") in names][-20:]
    return "\n".join(f"- {e['a']} ↔ {e['b']}：{clamp_summary(e.get('state'), 80)}（第{e.get('chapter')}章）" for e in hit)


# ------------------------------- 回查（L3） -------------------------------

_ASCII_WORD = re.compile(r"[a-z0-9_]{2,}")
_HAN = re.compile(r"[^\u4e00-\u9fa5]")


def _recall_terms(query: Any) -> list[str]:
    """关键词拆成词：中文按 2 字滑窗，英文/数字按词（顺序影响结果展示，按 JS Set 的插入顺序）。"""
    q = str(query or "").strip().lower()
    out: dict[str, None] = dict.fromkeys(_ASCII_WORD.findall(q))
    han = _HAN.sub("", q)
    for i in range(len(han) - 1):
        out.setdefault(han[i:i + 2], None)
    return list(out)


def _score(s: Any, terms: list[str]) -> int:
    low = str(s or "").lower()
    return sum(low.count(k) for k in terms)


def recall_memory(root: str | os.PathLike, *, query: Any, frm: Any = None, to: Any = None,
                  limit: int = 6, context: int = 160) -> dict[str, Any]:
    """按关键词回查：正文切片原文 + 记忆事件/摘要 + 伏笔/细纲命中，每段都带章号出处。"""
    terms = _recall_terms(query)
    if not terms:
        return {"ok": False, "text": "给一个关键词（至少两个字），比如人物名、地点、物件、伏笔名。", "hits": []}
    f = _num(frm) or 1
    t = _num(to) or math.inf
    idx = [c for c in _read_index(root) if f <= _num(c.get("number")) <= t]
    by_chapter = load_memory_rows(root)["byChapter"]
    fs_rows = read_jsonl(project_path(root, "ledger/foreshadow.jsonl"))
    out_rows = read_jsonl(project_path(root, "ledger/outline.jsonl"))

    hits = []
    for c in sorted(idx, key=lambda c: _num(c.get("number"))):
        m = by_chapter.get(_num(c.get("number"))) or {}
        s = _score("\n".join([
            str(c.get("title")), str(c.get("summary")), " ".join(str(x) for x in (c.get("characters") or [])),
            str(m.get("summary")), str(m.get("state")), " ".join(str(x) for x in (m.get("events") or [])),
        ]), terms)
        quote, where, text = "", "记忆", ""
        # 没摘要的老项目才翻原文；已有记忆的章不读全文（几百章全读会很慢）
        if not m.get("summary") and not c.get("summary") and c.get("file"):
            try:
                text = read_text(project_path(root, c["file"]))
            except OSError:
                text = ""
        if text:
            rex = re.compile("|".join(re.escape(k) for k in terms), re.IGNORECASE)
            mo = rex.search(text)
            if mo:
                at = mo.start()
                quote = re.sub(r"\s+", " ", text[max(0, at - context): at + context])
                where = "原文"
        total = s + (2 if quote else 0)
        if total > 0:
            hits.append({
                "chapter": _num(c.get("number")), "title": c.get("title") or "", "score": total, "where": where,
                "quote": quote, "summary": clamp_summary(m.get("summary") or c.get("summary") or "", 160),
            })
    for r in fs_rows:
        if not r or r.get("__corrupt"):
            continue
        s = _score(" ".join(str(r.get(k) or "") for k in ("name", "note", "source", "hint", "plantBeat")), terms)
        if s > 0:
            hits.append({
                "chapter": _num(r.get("plantedChapter")), "title": f"伏笔「{r.get('name')}」", "score": s,
                "where": "伏笔账", "quote": "｜".join(str(r[k]) for k in ("plantBeat", "hint", "source") if r.get(k)),
                "summary": r.get("note") or "",
            })
    for r in out_rows:
        if not r or r.get("__corrupt") or r.get("deleted"):
            continue
        s = _score(" ".join([
            " ".join(str(b) for b in (r.get("beats") or [])), str(r.get("openingState") or ""), str(r.get("endingState") or ""),
        ]), terms)
        if s > 0:
            first = next((b for b in (r.get("beats") or []) if any(k in str(b).lower() for k in terms)), None)
            hits.append({
                "chapter": _num(r.get("chapter")), "title": "细纲命中", "score": s, "where": "细纲",
                "quote": str(first or r.get("endingState") or ""), "summary": "",
            })
    hits.sort(key=lambda h: (-h["score"], h["chapter"]))
    top = hits[: max(1, min(20, _num(limit) or 6))]
    idx_by_num = {_num(c.get("number")): c for c in idx}
    cache: dict[int, str] = {}
    lines = []
    for h in top:
        heads = ""
        if h["where"] in ("原文", "记忆"):
            if h["chapter"] not in cache:
                row = idx_by_num.get(h["chapter"])
                try:
                    body = read_text(project_path(root, row["file"])) if row else ""
                    found = [line.strip()[:24] for line in body.split("\n")
                             if re.match(r"^\s*(\d+[.、]|#|第[一二三四五六七八九十百\d]+[节章])", line)]
                except (OSError, KeyError, TypeError):
                    found = []
                cache[h["chapter"]] = " / ".join(found[:5])
            heads = cache[h["chapter"]]
        lines.append(
            f"第{h['chapter']}章《{h['title']}》[{h['where']}]" + (f"\n小标题：{heads}" if heads else "")
            + f"\n{clamp_summary(h['quote'] or h['summary'] or '（命中标题/摘要）', 220)}"
        )
    return {
        "ok": True, "scope": {"terms": terms, "from": f, "to": (int(t) if t != math.inf else "末章")},
        "hits": top, "total": len(hits),
        "text": (
            f"回查「{query}」命中 {len(hits)} 处，按相关度给前 {len(top)} 处（带章号，可直接 novel_chapter op=read 看原文）：\n\n"
            + "\n\n".join(lines)
        ) if top else f"没找到「{query}」相关的记忆或正文。换个说法（人名/地点/物件/伏笔名）再查。",
    }


# ------------------------------- 技能路由 -------------------------------

SHORT_PLATFORMS = ["知乎", "盐言", "盐选", "黑岩", "点众", "短篇"]


def _is_short(opts: dict[str, Any] | None = None) -> bool:
    o = opts or {}
    if o.get("length") == "short":
        return True
    if o.get("length") == "long":
        return False
    return any(k in str(o.get("platform") or "") for k in SHORT_PLATFORMS)


# 「这一步该用哪个技能」的唯一定义处：面板/工具写进提示词，面板自己调模型时也拼同一份。
SKILL_ROUTES: dict[str, dict[str, Any]] = {
    "concept": {
        "use": lambda o: ["story-short-scan"] if _is_short(o) else ["story-long-scan"],
        "opt": lambda o: (["story-short-write"] if _is_short(o) else ["story-long-write"]) + (["agent-reach"] if o.get("ref") else []),
        "why": lambda o: (
            "先加载 `story-short-scan`（看知乎盐言/黑岩/点众什么短篇在爆），需要手感再叠 `story-short-write`。"
            if _is_short(o) else
            "先加载 `story-long-scan`（看起点/番茄/七猫的排行与新书趋势），需要开篇手感再叠 `story-long-write`。"
        )
        + "榜单只当参考，不要完全照着排行和新书趋势写，优先做有辨识度的选题。"
        + ("填了对标书时，自带网页搜索查不到的话用 `agent-reach` 再搜一次它的简介。" if o.get("ref") else ""),
    },
    "outline": {"use": lambda o: ["story-long-write"], "opt": lambda o: ["novel-creator"],
                "why": lambda o: "先加载 `story-long-write`（卷纲拆分与节奏），人物动机可选 `novel-creator`。"},
    "world": {"use": lambda o: ["novel-creator"], "opt": lambda o: ["story-long-write"],
              "why": lambda o: "先加载 `novel-creator`（世界架构 + 角色心理），要埋长线可选 `story-long-write`。"},
    "setup": {
        "use": lambda o: ["novel-creator"], "opt": lambda o: [],
        "why": lambda o: (
            "先加载 `novel-creator`，用角色心理拆人物卡（定位/欲望/恐惧/底线/缺陷/语言指纹）。"
            if o.get("scope") == "characters" else
            "先加载 `novel-creator`，用世界架构的方法拆势力/地点/物品/规则；这一轮不写人物卡。"
        ),
    },
    "foreshadow": {"use": lambda o: ["story-long-write"], "opt": lambda o: ["story-review"],
                   "why": lambda o: "先加载 `story-long-write`（长篇伏笔节奏），想先审已有承诺再叠 `story-review`。"},
    "outlines": {"use": lambda o: ["story-long-write"], "opt": lambda o: ["novel-creator"],
                 "why": lambda o: "先加载 `story-long-write`（每拍的目标-阻碍-变化），人物一致性可选 `novel-creator`。"},
    "write": {"use": lambda o: ["story-long-write", "novel-creator"], "opt": lambda o: [],
              "why": lambda o: "同时加载 `story-long-write`（按章节奏）与 `novel-creator`（人物欲望/缺陷一致）。"},
    "deslop": {"use": lambda o: ["story-deslop"], "opt": lambda o: ["humanizer"],
               "why": lambda o: "先加载 `story-deslop`（中文网文逐段改写）；英文/散文惯性再叠 `humanizer`。"},
    "review": {"use": lambda o: ["story-review"],
               "opt": lambda o: ["first-reader", "maoni-perspective", "fenghuo-perspective", "yuhua-perspective"],
               "why": lambda o: "先加载 `story-review`（多视角挑刺）；要真人感叠 `first-reader`，要作家视角只选其一。"},
    "memory": {"use": lambda o: [], "opt": lambda o: [], "why": lambda o: ""},
    "analyze": {"use": lambda o: ["story-long-analyze"], "opt": lambda o: ["story-short-analyze"],
                "why": lambda o: "长篇对标用 `story-long-analyze`，短篇对标用 `story-short-analyze`。"},
    "import": {"use": lambda o: ["story-import"], "opt": lambda o: [],
               "why": lambda o: "加载 `story-import`，按它的规则把已有稿子解析成项目目录。"},
    "cover": {"use": lambda o: ["story-cover"], "opt": lambda o: [], "why": lambda o: "加载 `story-cover`，按书名与题材出封面。"},
    "envcheck": {"use": lambda o: ["story-setup"], "opt": lambda o: [],
                 "why": lambda o: "加载 `story-setup`，核对技能与目录是否齐全。"},
}


def skill_block(action: str, opts: dict[str, Any] | None = None) -> str:
    """生成提示词末尾的「要加载的技能」几行；只列这一步真要用的。"""
    r = SKILL_ROUTES.get(action)
    if not r:
        return ""
    o = opts or {}
    use = [x for x in r["use"](o) if x]
    if not use:
        return ""
    opt = [x for x in r["opt"](o) if x]
    tag = lambda s: f"`{s}`"  # noqa: E731
    lines = [
        "【这一步要加载的技能】",
        f"- 必用：{'、'.join(tag(s) for s in use)}",
        f"- 可选（最多再叠一个）：{'、'.join(tag(s) for s in opt)}" if opt else "",
        f"- 为什么：{r['why'](o)}",
        "- 技能只给方法，事实一律以账本/工具返回为准；不要加载这里没列出的技能。",
    ]
    return "\n".join(x for x in lines if x)


# ------------------------------- 预算分配 -------------------------------

def _js_round(x: float) -> int:
    """JS Math.round：half-up（0.5 进位），Python round 是 half-even。"""
    return int(math.floor(x + 0.5))


def pack_budget(chars: Any) -> int:
    n = _num(chars)
    return min(24000, max(16000, _js_round(n * 3.2)))


def fit_sections(sections: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    """按段分配预算：必守段整段保留，可选段按权重平分剩余额度，各自截断并标注。

    sections: [{key,title,text,critical?,weight?,max?,min?}]
    """
    def cap(s: dict[str, Any], limit: float) -> str:
        text = str(s.get("text") or "")
        if len(text) <= limit:
            return text
        return text[: max(0, int(limit) - 1)].rstrip() + "…"

    critical = [s for s in sections if s.get("critical")]
    optional = [s for s in sections if not s.get("critical")]

    crit_out = []
    for s in critical:
        shortened = bool(s.get("max") and len(str(s.get("text") or "")) > s["max"])
        crit_out.append({
            "key": s["key"], "title": s["title"], "text": cap(s, s.get("max") or math.inf),
            "shortened": shortened,
        })
    critical_text = sum(len(x["text"]) for x in crit_out)

    remaining = max(0, budget - critical_text)
    mins = [min(_num(s.get("min")), len(str(s.get("text") or "")), s.get("max") or math.inf) for s in optional]
    pool = max(0, remaining - sum(mins))
    total_w = sum(s.get("weight", 1) for s in optional) or 1
    opt_out = []
    for i, s in enumerate(optional):
        text = str(s.get("text") or "")
        limit = mins[i] + math.floor(pool * s.get("weight", 1) / total_w)
        if s.get("max"):
            limit = min(limit, s["max"])
        if limit < 24:
            opt_out.append({"key": s["key"], "title": s["title"], "text": "", "skipped": True})
            continue
        out = text if len(text) <= limit else text[: max(0, int(limit) - 1)].rstrip() + "…"
        opt_out.append({"key": s["key"], "title": s["title"], "text": out, "truncated": len(out) < len(text)})

    all_out = [*crit_out, *opt_out]
    return {
        "sections": [x for x in all_out if x["text"]],
        "dropped": [x["title"] for x in crit_out if x.get("shortened")],
        "shortened": [x["title"] for x in opt_out if x.get("truncated")],
        "skipped": [x["title"] for x in opt_out if x.get("skipped")],
        "budget": budget,
        "used": sum(len(x.get("text") or "") for x in all_out),
    }
