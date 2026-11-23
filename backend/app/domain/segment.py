"""批次段落纲：批量写作时 10 章共用一份段落纲，不再每章一份细纲。

移植自 novel-studio/lib/segment.js。只做确定性拼装，不调模型；
数据全部来自 bible / 伏笔账 / 大纲 / 章节索引。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from ..store import append_jsonl, fold_segments, project_lock, read_json, read_jsonl
from ..store.paths import LAYOUT, project_path

SEGMENTS_FILE = "ledger/segments.jsonl"
MAX_RANGE = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _num(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _segments(root: str | os.PathLike) -> list[dict[str, Any]]:
    return fold_segments(read_jsonl(project_path(root, SEGMENTS_FILE)))


def _covers(seg: dict[str, Any], chapter: int) -> bool:
    return _num(seg.get("from")) <= chapter <= _num(seg.get("to"))


def _overlap_of(segments: list[dict[str, Any]], f: int, t: int, except_key: str = "") -> dict[str, Any] | None:
    for s in segments:
        if f"{s['from']}-{s['to']}" == except_key:
            continue
        if s["from"] <= t and f <= s["to"]:
            return s
    return None


def open_foreshadows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """折叠到当前状态，只留 open（未收/未放弃）的条目。"""
    current: dict[Any, dict[str, Any]] = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("__corrupt"):
            continue
        cur = current.get(r.get("id")) or {"id": r.get("id"), "status": "open"}
        op = r.get("op")
        status = "paid" if op == "payoff" else "abandoned" if op == "abandon" else (r.get("status") or cur.get("status"))
        current[r.get("id")] = {
            **cur,
            "name": r.get("name") if r.get("name") is not None else cur.get("name"),
            "plantedChapter": r.get("plantedChapter") if r.get("plantedChapter") is not None else cur.get("plantedChapter"),
            "dueChapter": r.get("dueChapter") if r.get("dueChapter") is not None else cur.get("dueChapter"),
            "status": status,
        }
    return [f for f in current.values() if f.get("status") == "open"]


def _outline_by_chapter(root: str | os.PathLike) -> dict[int, dict[str, Any] | None]:
    """读逐章细纲（兼容老模式）；批次模式下一般没有。"""
    out: dict[int, dict[str, Any] | None] = {}
    for r in read_jsonl(project_path(root, "ledger/outline.jsonl")):
        if not isinstance(r, dict) or r.get("__corrupt"):
            continue
        n = _num(r.get("chapter"))
        if n:
            out[n] = None if r.get("deleted") else r
    return out


def _split_range(f: int, t: int, stage_count: int) -> list[dict[str, Any]]:
    total = t - f + 1
    base, extra = divmod(total, stage_count)
    out, cur = [], f
    for _ in range(stage_count):
        size = base + (1 if extra > 0 else 0)
        if extra > 0:
            extra -= 1
        out.append({"from": cur, "to": cur + size - 1, "chapters": list(range(cur, cur + size))})
        cur += size
    return out


GOALS = [
    lambda who: f"{who}先拿到本段的第一条实证，但因此暴露一个弱点",
    lambda who: f"把「{who}想要的东西」推到不可退的位置，逼对手第一次正面出手",
    lambda who: "让本段的主要目标见分晓，同时留下下一段的引子",
    lambda who: f"处理上一台阶留下的代价，让{who}失去一个原本依赖的东西",
    lambda who: f"收束本段因果，把下一段的压力提前压到{who}身上",
]


def _pick_names(text: Any, names: list[str]) -> list[str]:
    t = str(text or "")
    return [n for n in names if n and n in t]


def plan_segment(root: str | os.PathLike, *, frm: Any = None, to: Any = None) -> dict[str, Any]:
    """规划一批段落纲（不写盘）。

    输出：{from,to,stages:[{chapters,goal,turn,foreshadow,pace,places,cast}],spine}
    """
    start = _num(frm) if frm is not None else 0
    if not isinstance(frm, int) and frm is not None:
        raise ValueError("planSegment 需要 from（起始章号，≥1 的整数）")
    if start <= 0:
        raise ValueError("planSegment 需要 from（起始章号，≥1 的整数）")
    end = start + 9 if to in (None, "") else _num(to)
    if end < start:
        raise ValueError(f"planSegment 的 to（{to}）必须是 ≥ from（{start}）的整数")
    if end - start + 1 > MAX_RANGE:
        raise ValueError(f"一段最多 {MAX_RANGE} 章，现在 {start}-{end} 有 {end - start + 1} 章")

    project = read_json(project_path(root, LAYOUT["project"]), None)
    if not project:
        raise FileNotFoundError(f"不是小说项目（缺 project.json）：{root}")
    bible = read_json(project_path(root, LAYOUT["bible"]), {}) or {}
    all_fs = open_foreshadows(read_jsonl(project_path(root, "ledger/foreshadow.jsonl")))
    outlines = _outline_by_chapter(root)

    chars = bible.get("characters") if isinstance(bible.get("characters"), list) else []

    def imp(c: Any) -> str:
        return str(c.get("importance") or c.get("tier") or "").strip() if isinstance(c, dict) else ""

    main = next((c for c in chars if imp(c) in ("核心", "主要", "S", "A")), None) or (chars[0] if chars else {})
    main = main if isinstance(main, dict) else {}
    concept = project.get("concept") if isinstance(project.get("concept"), dict) else {}
    who = str(main.get("name") or "主角")
    want = str(main.get("want") or concept.get("oneLine") or project.get("logline") or "推进主线目标")
    flaw = str(main.get("flaw") or main.get("fear") or "自己的执念")
    ability = str(main.get("ability") or "现有手段")
    rules = [r for r in (bible.get("rules") or []) if isinstance(r, dict) and (r.get("name") or r.get("text"))]
    rule_name = str((rules[0].get("name") or rules[0].get("text")) if rules else "这个世界的硬规则")[:40]
    places_all = [str(x.get("name") or "").strip() for x in (bible.get("locations") or []) if isinstance(x, dict)]
    places_all = [x for x in places_all if x]
    names_all = [str(c.get("name") or "").strip() for c in chars if isinstance(c, dict)]
    names_all = [x for x in names_all if x]

    total = end - start + 1
    # 3-5 个台阶：10 章默认 3 个；章节数不足 3 时台阶数不能超过章数，否则会拆出空台阶。
    # Math.round 是 half-up（4.5→5），Python round 是 half-even，所以显式算。
    stage_count = max(1, min(5, total, max(3, int(total / 3 + 0.5))))
    ranges = _split_range(start, end, stage_count)

    stages = []
    for i, r in enumerate(ranges):
        beats_text = " ".join(
            " ".join(str(x) for x in (o.get("title"), *(o.get("beats") or []), *(o.get("mustInclude") or [])) if x)
            for o in ((outlines.get(n) or {}) for n in r["chapters"])
        )
        plant = [str(f.get("name") or "").strip() for f in all_fs
                 if r["from"] <= _num(f.get("plantedChapter")) <= r["to"]]
        payoff = [str(f.get("name") or "").strip() for f in all_fs
                  if r["from"] <= _num(f.get("dueChapter")) <= r["to"]]
        plant = [x for x in plant if x]
        payoff = [x for x in payoff if x]
        places = _pick_names(beats_text, places_all)
        if not places and places_all:
            places = [places_all[i % len(places_all)]]
        cast = _pick_names(beats_text, names_all)
        stages.append({
            "chapters": r["chapters"],
            "goal": GOALS[min(i, len(GOALS) - 1)](who),
            "turn": f"{who}想靠{ability}硬推，结果触碰「{rule_name}」，{flaw}被对手抓住",
            "foreshadow": {"plant": plant, "payoff": payoff},
            "pace": "紧" if i % 2 == 0 else "缓",
            "places": places,
            "cast": cast or [who],
        })

    spine = str(project.get("logline") or concept.get("oneLine") or project.get("synopsis") or "").strip() or (
        f"{who}为了{want}，在第 {start}-{end} 章里先拿到实证、付出代价，再逼出对手的正面反应。"
    )
    return {"from": start, "to": end, "stages": stages, "spine": spine}


def write_segment_outline(root: str | os.PathLike, plan: dict[str, Any]) -> dict[str, Any]:
    """把段落纲落盘到 ledger/segments.jsonl（追加事件）。"""
    if not isinstance(plan, dict) or not plan.get("stages"):
        raise ValueError("writeSegmentOutline 需要 plan.stages（至少一个台阶）")
    f, t = _num(plan.get("from")), _num(plan.get("to"))
    if f <= 0 or t < f:
        raise ValueError("段落纲的 from/to 不合法")

    with project_lock(root):
        segments = _segments(root)
        hit = _overlap_of(segments, f, t)
        if hit:
            raise ValueError(
                f"第{f}-{t}章与已有批次第{hit['from']}-{hit['to']}章重叠；一批只能覆盖一段连续章号，"
                f"写第 {hit['to'] + 1} 章起请重新 plan"
            )
        covered = [int(n) for s in plan["stages"] for n in (s.get("chapters") or [])]
        want = list(range(f, t + 1))
        if covered != want:
            joined = ",".join(map(str, covered)) or "空"
            raise ValueError(f"段落纲的 stages 必须按顺序完整覆盖第{f}-{t}章（现在是 {joined}）")
        append_jsonl(project_path(root, SEGMENTS_FILE), {"kind": "segment", "from": f, "to": t, "plan": plan, "at": _now()})
        return {"ok": True, "from": f, "to": t, "stages": len(plan["stages"])}


def get_segment(root: str | os.PathLike, *, frm: Any = None, to: Any = None) -> dict[str, Any] | None:
    """读某段（from/to 精确匹配）或覆盖某章的最新段落纲。"""
    segments = _segments(root)
    if frm is not None and to is not None:
        f, t = _num(frm), _num(to)
        return next((s for s in segments if s["from"] == f and s["to"] == t), None)
    ch = _num(frm)
    if not ch:
        return segments[-1] if segments else None
    return next((s for s in reversed(segments) if _covers(s, ch)), None)


def chapter_from_segment(root: str | os.PathLike, chapter: Any) -> dict[str, Any] | None:
    """本章属于哪一批：段落纲 + 本章位置 + 批内已写章节摘要。老逐章模式返回 None。"""
    n = _num(chapter)
    if n <= 0:
        return None
    seg = get_segment(root, frm=n)
    if not seg:
        return None
    stages = (seg.get("plan") or {}).get("stages") or []
    stage_index = next((i for i, s in enumerate(stages) if n in [int(x) for x in (s.get("chapters") or [])]), -1)
    if stage_index < 0:
        return None
    index = read_json(project_path(root, LAYOUT["chapter_index"]), []) or []
    previous = [
        {"chapter": _num(c.get("number")), "title": c.get("title") or "",
         "summary": str(c.get("summary") or "")[:120]}
        for c in sorted(index, key=lambda c: _num(c.get("number")))
        if seg["from"] <= _num(c.get("number")) < n
    ]
    info = {
        "segment": seg.get("plan"),
        "from": seg["from"],
        "to": seg["to"],
        "stage": stages[stage_index],
        "stageIndex": stage_index,
        "stageCount": len(stages),
        "previous": previous,
    }
    info["text"] = segment_text(info)
    return info


def segment_text(info: dict[str, Any] | None, max_chars: int = 2500) -> str:
    """段落纲的可读文本（上下文包 / 工具返回共用）。"""
    if not info or not info.get("segment"):
        return ""
    segment = info["segment"]
    stage_index = info["stageIndex"]
    stage_count = info["stageCount"]
    lines = [
        f"本批：第{info['from']}-{info['to']}章（共 {stage_count} 个台阶）｜本章在第 {stage_index + 1} 个台阶",
        f"整段因果：{segment.get('spine') or '—'}",
    ]
    for i, s in enumerate(segment.get("stages") or []):
        fs = s.get("foreshadow") or {}
        chapters = "、".join(str(x) for x in (s.get("chapters") or []))
        lines.append(f"\n台阶{i + 1}（第{chapters}章）｜节奏：{s.get('pace') or '—'}{' ← 本章' if i == stage_index else ''}")
        lines.append(f"- 目标：{s.get('goal') or '—'}")
        lines.append(f"- 转折：{s.get('turn') or '—'}")
        if fs.get("plant"):
            lines.append(f"- 本台阶埋：{'、'.join(fs['plant'])}")
        if fs.get("payoff"):
            lines.append(f"- 本台阶收：{'、'.join(fs['payoff'])}")
        if s.get("places"):
            lines.append(f"- 预计现场：{'、'.join(s['places'])}")
    previous = info.get("previous") or []
    if previous:
        lines.append("\n批内已写：")
        for p in previous:
            lines.append(f"- 第{p['chapter']}章 {p['title']}｜{p['summary'] or '（无摘要）'}")
    else:
        lines.append("\n批内已写：本章是这一批的第一章。")
    lines.append(f"\n本章位置：第 {stage_index + 1}/{stage_count} 个台阶；只推进本台阶的「目标→转折」，不要把整批写完。")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def list_segments(root: str | os.PathLike) -> list[dict[str, Any]]:
    """供面板/工具列批次用；带上每个台阶的内容，面板才能直接显示段落纲正文。"""
    return [
        {
            "from": s["from"],
            "to": s["to"],
            "at": s.get("at"),
            "stages": len((s.get("plan") or {}).get("stages") or []),
            "spine": (s.get("plan") or {}).get("spine") or "",
            "plan": {
                "from": (s.get("plan") or {}).get("from"),
                "to": (s.get("plan") or {}).get("to"),
                "spine": (s.get("plan") or {}).get("spine") or "",
                "stages": (s.get("plan") or {}).get("stages") or [],
            },
        }
        for s in _segments(root)
    ]


def delete_segment(root: str | os.PathLike, *, frm: Any = None, to: Any = None) -> dict[str, Any]:
    """删除一段段落纲（from-to 精确定位）。已写正文不丢，那些章退回逐章模式。"""
    f, t = _num(frm), _num(to)
    if f <= 0 or t < f:
        raise ValueError(f"deleteSegment 需要合法的 from/to（现在是 {frm}-{to}）")
    with project_lock(root):
        hit = next((s for s in _segments(root) if s["from"] == f and s["to"] == t), None)
        if not hit:
            raise ValueError(f"没有第 {f}-{t} 章的段落纲")
        index = read_json(project_path(root, LAYOUT["chapter_index"]), []) or []
        written = [_num(c.get("number")) for c in index]
        append_jsonl(project_path(root, SEGMENTS_FILE), {"kind": "segment", "op": "delete", "from": f, "to": t, "at": _now()})
        return {"ok": True, "from": f, "to": t, "written": len([n for n in written if f <= n <= t])}
