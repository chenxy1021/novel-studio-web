"""审阅写操作：存档、退回、废章、正文保存、确定性体检、AI 改写/复检。

这里所有写操作都落项目目录（chapters/index.json、drafts/、ledger/review.jsonl、
project.json），不依赖浏览器 localStorage；换机器打开同一本书，审阅状态还在。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..llm import LLMError, chat, load_settings, strip_fence
from ..store import (
    LAYOUT,
    add_to_index,
    append_jsonl,
    ensure_dir,
    load_bible,
    load_project,
    pad3,
    project_lock,
    project_path,
    read_chapter,
    read_index,
    read_index_entry,
    read_jsonl,
    safe_join,
    save_project,
    write_chapter,
    write_index,
)
from ..store.jsonl import fold_foreshadow, fold_segments
from . import prompts as prompt_lib
from .memory import append_memory, build_echo_memory, clamp_summary
from .metrics import (
    check_chapter_end_hook,
    count_chars,
    detect_ai_tells,
    estimate_tokens,
    text_hash,
    text_metrics,
    verdict,
)
from .nuewen import REVERSALS as NUWEN_REVERSALS
from .platforms import check_platform_format, platform_brief, platform_rules
from .text import hard_rule_hits

MEMORY_FILE = "ledger/memory.jsonl"
CHECKS_FILE = "ledger/checks.jsonl"
# 复检提示词/标准改了就把版本号加一，旧的 AI 缓存自动失效。
AI_CHECK_VERSION = "2026-11-25.2"
REVIEW_FILE = "ledger/review.jsonl"
USAGE_FILE = "metrics/usage.jsonl"
SEGMENTS_FILE = "ledger/segments.jsonl"


class ReviewError(RuntimeError):
    """可预期的业务错误：路由层转 400。"""


class ChapterNotFound(ReviewError):
    status_code = 404


class ChapterConflict(ReviewError):
    status_code = 409


class ChapterBlocked(ChapterConflict):
    """体检有硬伤，必须先改或显式 force。"""

    def __init__(self, message: str, findings: list[dict[str, Any]]):
        super().__init__(message)
        self.findings = findings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ReviewError(f"不是小说项目（缺 project.json）：{root}")
    return project


def chapter_min_chars(project: dict[str, Any]) -> int:
    """作者在设置页写过 minChars 就听作者的；否则长篇默认 1800，≤50 章的短篇不限。"""
    explicit = project.get("minChars")
    if explicit not in (None, ""):
        try:
            return max(0, int(explicit))
        except (TypeError, ValueError):
            pass
    target = int(project.get("targetChapters") or 0)
    if 0 < target <= 50:
        return 0
    return int(os.environ.get("DSH_NOVEL_MIN_CHARS", "1800") or 0)


def _safe_name(text: Any, fallback: str) -> str:
    s = re.sub(r"[/\\:*?\"<>|]+", "_", str(text or "")).strip().strip(".")
    return s[:60] or fallback


def _severity(value: Any) -> str:
    return {"hard": "high", "high": "high", "mid": "mid", "info": "info"}.get(str(value), "info")


# 改写技能白名单：与前端弹窗、skills.SKILL_KEYS 的子集保持一致。
# 平台打法始终注入，不算可选技能；虐文公式跟随书级模式，也不在这里单列。
_REWRITE_SKILLS = ("deai", "dialogue", "scene", "hook", "continuity", "styleSamples")
_SKILL_LABELS = {
    "deai": "去 AI 味",
    "dialogue": "对话打磨",
    "scene": "场景落地",
    "hook": "章末钩子",
    "continuity": "连续性检查",
    "styleSamples": "文风样本",
}
# 技能 → prompts/ 模块；styleSamples 直接用已有样章，不加载模块。
_SKILL_MODULES = {
    "deai": "humanize",
    "dialogue": "dialogue",
    "scene": "scene",
    "hook": "hook",
    "continuity": "continuity",
}
_SKILL_MODULE_MAX_CHARS = 1600

# 六类语义复检分组，顺序固定；无问题的组也要返回 0 条。
_AI_GROUPS: tuple[tuple[str, str], ...] = (
    ("continuity", "吃书"),
    ("motivation", "动机"),
    ("voice", "口吻"),
    ("dialogue", "对话"),
    ("repetition", "信息重复"),
    ("emotion-summary", "情绪总结"),
)
_AI_GROUP_CODES = {code for code, _ in _AI_GROUPS}
_AI_GROUP_ALIASES = {
    "logic": "continuity",
    "foreshadow": "continuity",
    "setting": "continuity",
    "world": "continuity",
    "character": "voice",
    "tone": "voice",
    "style": "voice",
    "platform": "voice",
    "pacing": "dialogue",
    "scene": "dialogue",
    "info": "repetition",
    "repeat": "repetition",
    "duplicate": "repetition",
    "emotion": "emotion-summary",
    "summary": "emotion-summary",
}


def _group_of(code: Any) -> str:
    """把模型返回的 code 归到六类之一；认不出的按最接近的别名，再不行归口吻。"""
    raw = str(code or "").strip().lower()
    if raw in _AI_GROUP_CODES:
        return raw
    if raw in _AI_GROUP_ALIASES:
        return _AI_GROUP_ALIASES[raw]
    for code_, _ in _AI_GROUPS:
        if code_ in raw:
            return code_
    for alias, group in _AI_GROUP_ALIASES.items():
        if alias in raw:
            return group
    return "voice"


_AI_LIST_KEYS = ("findings", "issues", "problems", "results", "items", "data")


def _as_finding_list(value: Any) -> list[Any] | None:
    """把解析出来的 JSON 收敛成问题数组；对象里常见 findings/issues 之类的外壳也认。"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in _AI_LIST_KEYS:
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
        if any(key in value for key in ("message", "description", "hint", "severity")):
            return [value]
    return None


def _lenient_json(raw: str) -> Any:
    """严格 JSON 解析失败时，去掉尾逗号再试一次；都不行返回 None。"""
    for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            return json.loads(attempt)
        except (TypeError, ValueError):
            continue
    return None


def _parse_finding_array(raw: Any) -> list[Any] | None:
    """从模型输出里尽量抠出问题数组；抠不出返回 None，由调用方修复或报错。"""
    text = strip_fence(str(raw or "")).strip()
    if not text:
        return None
    start, end = text.find("["), text.rfind("]")
    candidates = [text]
    if 0 <= start < end:
        candidates.append(text[start: end + 1])
    for candidate in candidates:
        parsed = _as_finding_list(_lenient_json(candidate))
        if parsed is not None:
            return parsed
    # 退一步：整段是个对象（{"findings": [...]} 或单条问题）
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        parsed = _as_finding_list(_lenient_json(text[start: end + 1]))
        if parsed is not None:
            return parsed
    return None


def _thinking_text(result: dict[str, Any], raw: str) -> str:
    """优先用模型的 reasoning_content；没有就取 JSON 数组前面的审稿思路。"""
    native = str(result.get("reason") or "").strip()
    if native:
        return native
    cut = raw.find("[")
    preface = (raw[:cut] if cut > 0 else "").strip()
    return preface[:4000]


# 复检标准：没有证据（引用本章原句 / 细纲原句）的不算问题；上限防止凑数。
_AI_MAX_FINDINGS = 6
_AI_MAX_HIGH = 3


def _compact(value: Any) -> str:
    return re.sub(r"[\s　]+", "", str(value or ""))


def _outline_phrases(outline_brief: str) -> list[str]:
    """细纲里「必须出现 / 必须回避」的条目原文，用来核对「缺拍」类问题的依据。"""
    out: list[str] = []
    for line in str(outline_brief or "").splitlines():
        _, sep, tail = line.partition("：")
        if not sep:
            continue
        for part in tail.split("；"):
            key = _compact(part)
            if len(key) >= 4:
                out.append(key)
    return out


def _grounded_ai_findings(
    parsed: list[Any],
    body: str,
    outline_brief: str,
    n: int,
) -> tuple[list[dict[str, Any]], int]:
    """只留下能落到证据上的问题：quote 必须在本章正文里逐字出现；
    细纲缺失类没有原句，basis 必须逐字引用细纲条目。返回 (findings, 被拒条数)。"""
    body_key = _compact(body)
    phrases = _outline_phrases(outline_brief)
    out: list[dict[str, Any]] = []
    seen: list[tuple[str, str]] = []
    high = 0
    dropped = 0
    for item in parsed:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        quote = str(item.get("quote") or "").strip()
        basis = str(item.get("basis") or "").strip()
        quote_key = _compact(quote)
        grounded = len(quote_key) >= 4 and quote_key in body_key
        if not grounded and basis:
            basis_key = _compact(basis)
            grounded = bool(basis_key) and any(p in basis_key or basis_key in p for p in phrases)
        if not grounded:
            dropped += 1
            continue

        code = str(item.get("code") or "ai-review")[:40]
        group = _group_of(code)
        severity = _severity(item.get("severity"))
        if severity == "info":
            dropped += 1
            continue
        # 同一段最多留 2 条：改一段就能一起解决，避免「一段里塞五条，改完还剩三条」。
        paragraph = _paragraph_index(body, quote)
        if paragraph and sum(1 for f in out if f.get("paragraph") == paragraph) >= 2:
            dropped += 1
            continue
        message_key = _compact(message)
        if any(g == group and (message_key in mk or mk in message_key) for g, mk in seen):
            dropped += 1
            continue
        if severity == "high" and high >= _AI_MAX_HIGH:
            severity = "mid"
        if severity == "high":
            high += 1
        seen.append((group, message_key))
        out.append({
            "severity": severity,
            "code": code,
            "group": group,
            "message": message[:300],
            "quote": quote[:160],
            "basis": basis[:200],
            "hint": str(item.get("hint") or "")[:300],
            # 段落定位：面板上的「改这一段」按它改，改完按 quote 验证。
            "paragraph": paragraph,
            "chapter": n,
            "source": "ai",
        })
        if len(out) >= _AI_MAX_FINDINGS:
            break
    # 固定顺序：模型换个说法时，同一组问题不要因为出现先后不同而看起来像换了结果。
    group_order = {code: i for i, (code, _) in enumerate(_AI_GROUPS)}
    out.sort(key=lambda f: (
        0 if f["severity"] == "high" else 1,
        group_order.get(f["group"], len(group_order)),
        f["message"],
    ))
    return out, dropped


def _target_chars(project: dict[str, Any], rules: dict[str, Any]) -> int:
    """单章目标字数：书级 wordsPerChapter 优先，其次平台下限。"""
    return int(project.get("wordsPerChapter") or 0) or int(rules.get("wordsMin") or 0)


def _ai_tells_payload(body: str, tells: list[dict[str, Any]], level: dict[str, Any]) -> dict[str, Any]:
    """确定性 AI 痕迹的结构化结果：分类、样例、定位，供体检面板直接渲染。"""
    categories = []
    for tell in tells:
        categories.append({
            "id": tell["id"],
            "label": tell["label"],
            "severity": tell["severity"],
            "count": tell["count"],
            "per1000": tell.get("per1000", 0.0),
            "samples": [
                {
                    "text": str(s.get("text") or ""),
                    "paragraph": int(s.get("paragraph") or 1),
                    "offset": int(s.get("offset") or 0),
                    "line": int(s.get("line") or 0),
                }
                for s in (tell.get("samples") or [])
            ],
        })
    return {
        "level": level["level"],
        "verdict": level,
        "total": sum(t["count"] for t in tells),
        "density": level["density"],
        "categories": categories,
    }


def _suggest_skills(
    bible: dict[str, Any],
    tells: list[dict[str, Any]],
    level: dict[str, Any],
    hook: dict[str, Any],
    hard: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[str]:
    """按 §15.4 预选改写技能；只返回白名单内的 id，按固定顺序去重。"""
    picked: set[str] = set()
    codes = {str(f.get("code") or "") for f in findings}

    if level["level"] == "差" or any(t["severity"] == "high" for t in tells):
        picked.add("deai")
    if any(c in ("voice", "dialogue") or "dialogue" in c for c in codes):
        picked.add("dialogue")
    if any(c in ("pacing", "scene", "rhythm") or "pacing" in c for c in codes):
        picked.add("scene")
    if not hook.get("ok"):
        picked.add("hook")
    if hard or any(c in ("continuity", "foreshadow", "logic") or "hard" in c for c in codes):
        picked.add("continuity")

    style = bible.get("style") if isinstance(bible.get("style"), dict) else {}
    samples = style.get("samples") if isinstance(style.get("samples"), list) else []
    if samples:
        picked.add("styleSamples")

    # 没有任何硬伤/需改/钩子问题：保守组合，仍有得改（去 AI 味 + 连续性）。
    has_problem = (
        bool(hard)
        or not hook.get("ok")
        or any(f.get("severity") in ("high", "mid") for f in findings)
        or any(t["severity"] in ("high", "mid") for t in tells)
    )
    if not has_problem:
        picked.update(("deai", "continuity"))

    return [skill for skill in _REWRITE_SKILLS if skill in picked]


# --------------------------------- 体检 ---------------------------------


def check_chapter(root: str | os.PathLike, number: int) -> dict[str, Any]:
    """确定性体检：字数、平台格式、AI 痕迹、章尾钩子、规则。不调模型，可离线跑。"""
    project = _project(root)
    n = int(number)
    entry = read_index_entry(root, n)
    if not entry:
        raise ChapterNotFound(f"没有第{n}章")
    try:
        body = read_chapter(root, n) or ""
    except FileNotFoundError:
        body = ""

    m = text_metrics(body)
    tells = detect_ai_tells(body)
    level = verdict(m, tells)
    hook = check_chapter_end_hook(body)
    bible = load_bible(root)
    hard = hard_rule_hits(bible.get("rules") or [], body)

    findings: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, hint: str = "") -> None:
        findings.append({"severity": _severity(severity), "code": code, "message": message, "hint": hint, "chapter": n})

    prules = platform_rules(project.get("platform"))
    platform = check_platform_format(
        body,
        entry.get("title"),
        m,
        prules,
        {"minChars": chapter_min_chars(project)},
    )
    for issue in platform["issues"]:
        add(issue["severity"], issue["code"], issue["message"],
            "补到下限/删到上限，或把长段拆开" if issue["severity"] != "info" else "平台建议，不拦存档")

    for tell in tells[:6]:
        if tell["severity"] not in ("high", "mid"):
            continue
        sample = "；".join(x["text"] for x in tell.get("samples") or [] if x.get("text"))
        add(tell["severity"], f"ai-tell-{tell['id']}", f"{tell['label']} ×{tell['count']}",
            f"改写命中句：{sample}" if sample else "换成具体动作或人物反应")

    if hard:
        for hit in hard[:5]:
            add("high", "hard-rule", f"撞规则「{hit['rule']}」：{hit['matched']}", "按设定换一个不违反规则的做法")

    if not hook.get("ok"):
        add("info", "no-end-hook", f"第{n}章{hook.get('reason') or '章尾偏弱'}",
            "补发现/反转、意外动作、被打断、倒计时或短句留白")

    if level["level"] == "差":
        add("high", "ai-verdict", f"AI 痕迹判定「差」（{level['high']} 条 high，密度 {level['density']}/千字）",
            "按上面的命中句逐条改，不要整章推倒重来")

    rank = {"high": 0, "mid": 1, "info": 2}
    findings.sort(key=lambda f: rank.get(f["severity"], 3))

    # RuleChip 行：字数 / 对话比 / 章尾钩子 / 规则 / 平台格式。
    rules_out: list[dict[str, Any]] = []
    target = _target_chars(project, prules)
    if target > 0:
        lo, hi = int(round(target * 0.75)), int(round(target * 1.2))
        if m["chars"] < lo:
            chars_state, chars_msg = "bad", f"{m['chars']} 字，低于目标 {target} 字的 75%（{lo} 字）"
        elif m["chars"] > hi:
            chars_state, chars_msg = "warn", f"{m['chars']} 字，超过目标 {target} 字的 120%（{hi} 字）"
        else:
            chars_state, chars_msg = "ok", f"{m['chars']} 字，在目标 {target} 字的 75%–120% 内"
        rules_out.append({
            "id": "chars", "label": "字数", "state": chars_state,
            "value": m["chars"], "limit": {"min": lo, "max": hi}, "message": chars_msg,
        })
    else:
        rules_out.append({
            "id": "chars", "label": "字数", "state": "ok",
            "value": m["chars"], "limit": None, "message": f"{m['chars']} 字（未设目标字数）",
        })

    dialogue_min = float(prules.get("dialogueMin") or 0)
    dialogue_ok = dialogue_min <= 0 or m["dialogueRatio"] >= dialogue_min
    rules_out.append({
        "id": "dialogue", "label": "对话比", "state": "ok" if dialogue_ok else "warn",
        "value": m["dialogueRatio"], "limit": dialogue_min,
        "message": (
            f"对话比 {m['dialogueRatio'] * 100:.0f}%"
            + ("" if dialogue_min <= 0 else f"，平台建议不低于 {dialogue_min * 100:.0f}%")
        ),
    })

    rules_out.append({
        "id": "endHook", "label": "章尾钩子", "state": "ok" if hook.get("ok") else "warn",
        "value": bool(hook.get("ok")), "limit": None, "message": hook.get("reason") or "",
    })

    for hit in hard:
        rules_out.append({
            "id": "hardRule", "label": "规则", "state": "bad",
            "value": hit["matched"], "limit": hit["rule"],
            "message": f"撞规则「{hit['rule']}」：{hit['matched']}",
        })

    covered = {"words-below", "words-above", "dialogue-low"}
    for issue in platform["issues"]:
        if issue["code"] in covered:
            continue
        rules_out.append({
            "id": "platform", "label": "平台格式",
            "state": "bad" if issue["severity"] == "hard" else "warn",
            "value": issue["code"], "limit": None, "message": issue["message"],
        })

    ai_tells = _ai_tells_payload(body, tells, level)
    return {
        "number": n,
        "pass": not any(f["severity"] == "high" for f in findings),
        "findings": findings,
        "canRewrite": True,
        "chars": m["chars"],
        "dialogueRatio": m["dialogueRatio"],
        "endHook": hook,
        "verdict": level,
        "aiTells": ai_tells,
        "rules": rules_out,
        "checkedAt": _now(),
        "textHash": text_hash(body),
        "suggestedSkills": _suggest_skills(bible, tells, level, hook, hard, findings),
    }


def check_batch(root: str | os.PathLike, frm: Any = None, to: Any = None) -> dict[str, Any]:
    """按批体检：逐章确定性检查 + 跨章提醒（到期伏笔）。"""
    project = _project(root)
    index = read_index(root)
    if not index:
        return {"from": 0, "to": 0, "chapters": [], "blocking": [], "checkedAt": _now()}

    start = int(frm or 0)
    end = int(to or 0)
    if start <= 0 or end <= 0:
        gate = project.get("gate") or {}
        # gate.chapter 指向「下一章要写的」，比已写章大 1；体检要看已写的那一批。
        cur = int(project.get("currentChapter") or gate.get("chapter") or max(int(c["number"]) for c in index))
        segs = fold_segments(read_jsonl(project_path(root, SEGMENTS_FILE)))
        seg = next((s for s in segs if int(s["from"]) <= cur <= int(s["to"])), None)
        if not seg:
            seg = next((s for s in segs if int(s["from"]) <= cur - 1 <= int(s["to"])), None)
        if seg:
            start, end = int(seg["from"]), int(seg["to"])
        else:
            end = cur
            start = max(1, end - 9)
    if end < start:
        start, end = end, start

    rows = [c for c in index if start <= int(c["number"]) <= end]
    chapters = [check_chapter(root, int(c["number"])) for c in rows]

    fores = fold_foreshadow(read_jsonl(project_path(root, "ledger/foreshadow.jsonl")))
    overdue = sorted(
        (
            f for f in fores
            if f.get("status") == "open" and f.get("dueChapter") not in (None, "")
            and int(f.get("dueChapter") or 0) <= end
        ),
        key=lambda f: (int(f.get("dueChapter") or 0), str(f.get("name") or "")),
    )
    blocking: list[dict[str, Any]] = []
    if overdue:
        names = "、".join(str(f.get("name")) for f in overdue[:5])
        more = f" 等 {len(overdue)} 条" if len(overdue) > 5 else ""
        blocking.append({
            "severity": "mid",
            "code": "foreshadow-overdue",
            "message": f"{len(overdue)} 条伏笔已经到期还没收：{names}{more}",
            "hint": "是已经写进正文了就标「已收」，这条线不打算写了就点「放弃」；处理完再体检一次。",
            "items": [
                {
                    "id": str(f.get("id") or ""),
                    "name": str(f.get("name") or ""),
                    "kind": str(f.get("kind") or "detail"),
                    "plantedChapter": int(f.get("plantedChapter") or 0),
                    "dueChapter": int(f.get("dueChapter") or 0),
                    "overdueBy": max(0, end - int(f.get("dueChapter") or 0)),
                }
                for f in overdue
            ],
        })
    return {"from": start, "to": end, "chapters": chapters, "blocking": blocking, "checkedAt": _now()}


# ------------------------------ 体检结果缓存 ------------------------------ #


def record_check(root: str | os.PathLike, result: dict[str, Any]) -> None:
    """把一次确定性体检落账，刷新页面后还能看到上次结果。

    体检是派生数据，按 textHash 判断是否还对上当前正文；对不上就标记 stale，
    不让旧结果冒充新结果。
    """
    chapter = int(result.get("number") or 0)
    if chapter <= 0:
        return
    append_jsonl(project_path(root, CHECKS_FILE), {
        "kind": "check",
        "chapter": chapter,
        "textHash": str(result.get("textHash") or ""),
        "at": str(result.get("checkedAt") or _now()),
        "result": result,
    })


def _ai_finding_key(f: dict[str, Any]) -> tuple[str, str]:
    return str(f.get("code") or ""), str(f.get("message") or "")


def active_ai_round(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    """这一章进行中的复检轮次：{'row': ..., 'resolved': {(code, message)}}。

    一轮复检只在三种情况下结束：整章改写（稿子换了）、退稿、作者自己重扫。
    段落改写属于「就地修」，轮次保留，修掉的条目记 resolve，不再重新出题。
    """
    rows = read_jsonl(project_path(root, CHECKS_FILE))
    active: dict[str, Any] | None = None
    resolved: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("__corrupt"):
            continue
        if int(row.get("chapter") or 0) != int(chapter):
            continue
        kind = row.get("kind")
        if kind == "ai-round":
            if row.get("version") != AI_CHECK_VERSION or not isinstance(row.get("result"), dict):
                active = None
                resolved = set()
                continue
            active = row
            resolved = set()
        elif not active:
            continue
        elif kind == "ai-round-close" and row.get("round") == active.get("round"):
            active = None
            resolved = set()
        elif kind == "ai-round-resolve" and row.get("round") == active.get("round"):
            resolved.add((str(row.get("code") or ""), str(row.get("message") or "")))
    if active is None:
        return None
    return {"row": active, "resolved": resolved}


def record_ai_round(
    root: str | os.PathLike, result: dict[str, Any], context_hash: str, round_id: str,
) -> None:
    """开一轮 AI 复检。之后同一章再点复检，返回的是这一轮修完剩下的条目。"""
    chapter = int(result.get("number") or 0)
    if chapter <= 0:
        return
    append_jsonl(project_path(root, CHECKS_FILE), {
        "kind": "ai-round",
        "chapter": chapter,
        "round": round_id,
        "version": AI_CHECK_VERSION,
        "textHash": str(result.get("textHash") or ""),
        "contextHash": context_hash,
        "at": str(result.get("checkedAt") or _now()),
        "result": result,
    })


def close_ai_round(root: str | os.PathLike, chapter: int, why: str) -> None:
    """稿子整体换了或章节退了：这一轮的条目不再对应当前正文，下一轮重新出题。"""
    active = active_ai_round(root, chapter)
    if not active:
        return
    append_jsonl(project_path(root, CHECKS_FILE), {
        "kind": "ai-round-close",
        "chapter": int(chapter),
        "round": active["row"].get("round"),
        "why": why,
        "at": _now(),
    })


def mark_ai_resolved(
    root: str | os.PathLike, chapter: int, code: str, message: str, how: str = "manual",
) -> None:
    """把一轮里的一条记成已解决：段落改到原句消失，或作者手动确认。"""
    active = active_ai_round(root, chapter)
    if not active or not message:
        return
    append_jsonl(project_path(root, CHECKS_FILE), {
        "kind": "ai-round-resolve",
        "chapter": int(chapter),
        "round": active["row"].get("round"),
        "code": str(code or ""),
        "message": str(message),
        "how": how,
        "at": _now(),
    })


def _round_payload(root: str | os.PathLike, active: dict[str, Any]) -> dict[str, Any] | None:
    """把一轮复检按已解决的条目过滤后返回；确定性层用当前正文重跑。"""
    row = active["row"]
    stored = row.get("result")
    if not isinstance(stored, dict):
        return None
    chapter = int(row.get("chapter") or 0)
    try:
        base = check_chapter(root, chapter)
    except Exception:  # noqa: BLE001 - 章没了就当作没有这一轮
        return None
    resolved = active["resolved"]

    def keep(f: dict[str, Any]) -> bool:
        return _ai_finding_key(f) not in resolved

    stored_findings = [f for f in (stored.get("findings") or []) if isinstance(f, dict)]
    ai_findings = [f for f in stored_findings if f.get("source") == "ai" and keep(f)]
    groups = []
    for g in stored.get("groups") or []:
        kept = [f for f in (g.get("findings") or []) if isinstance(f, dict) and keep(f)]
        groups.append({**g, "count": len(kept), "findings": kept})
    if not groups:
        groups = [
            {"code": code, "label": label, "count": 0, "findings": []}
            for code, label in _AI_GROUPS
        ]
    high = sum(1 for f in ai_findings if f.get("severity") == "high")
    mid = sum(1 for f in ai_findings if f.get("severity") == "mid")
    standard = dict(stored.get("standard") or {})
    standard.update({
        "verdict": "fail" if high else "minor" if mid else "pass",
        "high": high,
        "mid": mid,
    })
    rank = {"high": 0, "mid": 1, "info": 2}
    merged = list(base.get("findings") or []) + ai_findings
    merged.sort(key=lambda f: (rank.get(f.get("severity"), 3), str(f.get("code") or ""), str(f.get("message") or "")))
    return {
        **stored,
        "number": chapter,
        "pass": not any(f.get("severity") == "high" for f in merged),
        "findings": merged,
        "groups": groups,
        "standard": standard,
        "canRewrite": True,
        "chars": base["chars"],
        "dialogueRatio": base["dialogueRatio"],
        "endHook": base["endHook"],
        "verdict": base["verdict"],
        "aiTells": base["aiTells"],
        "rules": base["rules"],
        "checkedAt": base["checkedAt"],
        "textHash": base["textHash"],
        "suggestedSkills": base["suggestedSkills"],
        "round": row.get("round"),
        "roundAt": str(row.get("at") or ""),
        # 只数真的在本轮里、且被摘掉的条目。
        "resolvedCount": sum(
            1 for f in stored_findings
            if f.get("source") == "ai" and _ai_finding_key(f) in resolved
        ),
        # 这一轮没有重新问模型，只是把修完的条目摘掉。
        "cached": True,
        "carried": True,
    }


def carried_ai_check(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    """进行中轮次的当前状态；没有轮次返回 None。"""
    active = active_ai_round(root, chapter)
    if not active:
        return None
    return _round_payload(root, active)


def resolve_ai_finding(
    root: str | os.PathLike, chapter: int, code: str, message: str, how: str = "manual",
) -> dict[str, Any]:
    """作者确认某条问题已解决；不重新扫，只把它从这一轮里摘掉。"""
    active = active_ai_round(root, chapter)
    if not active:
        raise ReviewError("这一章没有进行中的 AI 复检，先做一次复检")
    stored = active["row"].get("result") or {}
    keys = {
        _ai_finding_key(f)
        for f in (stored.get("findings") or [])
        if isinstance(f, dict) and f.get("source") == "ai"
    }
    key = (str(code or ""), str(message or ""))
    if key not in keys:
        raise ReviewError("这条问题不在本轮复检里，可能已经处理过；刷新复检再看")
    if key not in active["resolved"]:
        mark_ai_resolved(root, chapter, code, message, how=how)
    payload = carried_ai_check(root, chapter)
    if payload is None:
        raise ReviewError("这一轮的复检结果读不出来，重新做一次复检")
    return payload


def _ai_context_hash(prompt: str, model: str) -> str:
    """提示词里已经包含正文、前情、上一章结尾、细纲、人物与规则，哈希它就是全部输入。"""
    raw = f"{AI_CHECK_VERSION}\x1f{model}\x1f{prompt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_checks(root: str | os.PathLike) -> list[dict[str, Any]]:
    """每章取最近一次体检；stale=True 表示正文在体检后改过。"""
    rows = read_jsonl(project_path(root, CHECKS_FILE))
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("__corrupt") or row.get("kind") != "check":
            continue
        chapter = int(row.get("chapter") or 0)
        if chapter > 0 and isinstance(row.get("result"), dict):
            latest[chapter] = row
    out: list[dict[str, Any]] = []
    for chapter in sorted(latest):
        row = latest[chapter]
        try:
            body = read_chapter(root, chapter) or ""
        except (FileNotFoundError, OSError):
            continue  # 章已经被退掉，缓存不再返回
        out.append({
            "chapter": chapter,
            "at": str(row.get("at") or ""),
            "stale": text_hash(body) != str(row.get("textHash") or ""),
            "result": row["result"],
        })
    return out


# --------------------------------- 存档 ---------------------------------


def archive_chapter(root: str | os.PathLike, number: int, *, force: bool = False) -> dict[str, Any]:
    with project_lock(root):
        project = _project(root)
        n = int(number)
        entry = read_index_entry(root, n)
        if not entry:
            raise ChapterNotFound(f"第{n}章不存在，无法存档")
        if entry.get("approved"):
            raise ChapterConflict(f"第{n}章已经存档过了")
        check = check_chapter(root, n)
        if not check["pass"] and not force:
            high = [f for f in check["findings"] if f["severity"] == "high"]
            detail = "；".join(f"{f['message']}" for f in high[:3])
            raise ChapterBlocked(f"第{n}章还有 {len(high)} 条硬伤：{detail}。先改，或确认要照收。", high)

        at = _now()
        index = read_index(root)
        for row in index:
            if int(row.get("number") or 0) == n:
                row["approved"] = True
                row["approvedAt"] = row.get("approvedAt") or at
                break
        write_index(root, index)

        numbers = [int(c["number"]) for c in index if int(c.get("number") or 0) > 0]
        project["currentChapter"] = max(numbers) if numbers else 0
        next_chapter = n + 1
        project["gate"] = {
            "phase": "writing",
            "chapter": next_chapter,
            "reason": f"第{n}章已通过，开始写第{next_chapter}章",
            "at": at,
        }
        if isinstance(project.get("rewriteCounts"), dict):
            project["rewriteCounts"].pop(str(n), None)
        save_project(root, project)

        # 通过即写摘要级章记忆；模型不可用时也至少有一条可检索的记录。
        append_memory(root, {
            "chapter": n,
            "title": entry.get("title") or "",
            "summary": clamp_summary(entry.get("summary") or "", 240),
            "events": [],
            "state": "",
            "characters": entry.get("characters") or [],
            "source": "index",
        })
        return {
            "ok": True,
            "approved": n,
            "nextChapter": next_chapter,
            "chapter": read_index_entry(root, n),
            "gate": project["gate"],
        }


# --------------------------------- 退回 ---------------------------------


def reject_chapter(root: str | os.PathLike, number: int, reason: str = "") -> dict[str, Any]:
    """真退稿：旧稿进 drafts/，章号从正文索引释放，可立刻重写同一章。"""
    with project_lock(root):
        project = _project(root)
        n = int(number)
        index = read_index(root)
        hit = next((c for c in index if int(c.get("number") or 0) == n), None)
        if not hit:
            raise ChapterNotFound(f"第{n}章不在正文里，无法退回")

        body = ""
        try:
            body = read_chapter(root, n) or ""
        except FileNotFoundError:
            pass
        title = str(hit.get("title") or "")
        ensure_dir(project_path(root, LAYOUT["drafts"]))
        draft_name = f"{pad3(n)}-{_safe_name(title, '未命名')}-reject-{int(datetime.now().timestamp() * 1000):x}.md"
        draft_rel = f"{LAYOUT['drafts']}/{draft_name}"
        if body:
            Path(project_path(root, draft_rel)).write_text(body, encoding="utf-8")

        remaining = [c for c in index if int(c.get("number") or 0) != n]
        write_index(root, remaining)
        if hit.get("file"):
            try:
                os.unlink(safe_join(root, str(hit["file"])))
            except FileNotFoundError:
                pass

        append_jsonl(project_path(root, REVIEW_FILE), {
            "kind": "discard",
            "number": n,
            "title": title,
            "reason": reason or "作者退回重写",
            "draftFile": draft_rel if body else "",
            "at": _now(),
        })

        numbers = [int(c["number"]) for c in remaining if int(c.get("number") or 0) > 0]
        project["currentChapter"] = max(numbers) if numbers else 0
        if isinstance(project.get("rewriteCounts"), dict):
            project["rewriteCounts"].pop(str(n), None)
        project["gate"] = {
            "phase": "writing",
            "chapter": n,
            "reason": f"第{n}章已退回，可重写这一章",
            "at": _now(),
        }
        save_project(root, project)

    # 章已经摘出正文索引：派生数据跟着退。章记忆本身不删（恢复时自动再用），
    # 但并进 bible 的位置 / 转手 / 状态要回退，否则下一章会带着被退稿的设定写。
    try:
        from . import continuity, memory_gen

        continuity.undo_chapter(root, n)
        memory_gen.retract_volume_memory(root, n)
    except Exception:  # noqa: BLE001 - 派生数据回退失败不该让退稿失败
        pass
    close_ai_round(root, n, "reject")
    return {"ok": True, "discarded": n, "draftFile": draft_rel if body else "", "chapter": None}


# --------------------------------- 废章 ---------------------------------


def list_discarded(root: str | os.PathLike) -> list[dict[str, Any]]:
    rows = read_jsonl(project_path(root, REVIEW_FILE))
    restored = {int(r.get("number") or 0) for r in rows if r.get("kind") == "restore"}
    purged = {str(r.get("draftFile") or "") for r in rows if r.get("kind") == "purge"}
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") not in ("discard", "rewrite"):
            continue
        rel = str(row.get("draftFile") or "")
        if rel and rel in purged:
            continue
        if int(row.get("number") or 0) in restored:
            continue
        text = ""
        if rel:
            try:
                text = safe_join(root, rel).read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
        flat = re.sub(r"\s+", " ", text).strip()
        out.append({
            "number": int(row.get("number") or 0),
            "title": row.get("title") or "",
            "reason": row.get("reason") or "",
            "chars": count_chars(flat),
            "at": row.get("at") or "",
            "draftFile": rel,
            "lead": flat[:60],
        })
    out.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    return out


def read_discarded(root: str | os.PathLike, draft_file: str) -> dict[str, Any]:
    if not draft_file:
        raise ReviewError("缺少 draftFile")
    try:
        p = safe_join(root, draft_file)
    except PermissionError as e:
        raise ReviewError(str(e)) from e
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ChapterNotFound("草稿文件不存在，可能已被手动删除") from e
    return {"ok": True, "draftFile": draft_file, "text": text, "chars": count_chars(text)}


def purge_discarded(root: str | os.PathLike, draft_file: str) -> dict[str, Any]:
    if not draft_file:
        raise ReviewError("缺少 draftFile")
    with project_lock(root):
        try:
            safe_join(root, draft_file).unlink(missing_ok=True)
        except PermissionError as e:
            raise ReviewError(str(e)) from e
        append_jsonl(project_path(root, REVIEW_FILE), {"kind": "purge", "draftFile": draft_file, "at": _now()})
    return {"ok": True, "removed": True, "draftFile": draft_file}


def restore_discarded(root: str | os.PathLike, draft_file: str, number: int = 0, title: str = "") -> dict[str, Any]:
    data = read_discarded(root, draft_file)
    text = data["text"]
    with project_lock(root):
        project = _project(root)
        index = read_index(root)
        numbers = [int(c["number"]) for c in index if int(c.get("number") or 0) > 0]
        n = int(number or 0) or (max(numbers) + 1 if numbers else 1)
        prior = next(
            (r for r in read_jsonl(project_path(root, REVIEW_FILE))
             if r.get("kind") in ("discard", "rewrite") and str(r.get("draftFile") or "") == draft_file),
            {},
        )
        entry_title = title.strip() or str(prior.get("title") or "").strip() or f"第{n}章"
        _, rel = write_chapter(root, n, entry_title, text)
        row = _entry_from_text({"number": n, "title": entry_title, "file": rel,
                                "summary": "", "characters": [], "approved": False}, text)
        add_to_index(root, row)
        append_jsonl(project_path(root, REVIEW_FILE), {
            "kind": "restore", "number": n, "draftFile": draft_file, "at": _now(),
        })
        project["currentChapter"] = max(max(numbers), n) if numbers else n
        project["gate"] = {
            "phase": "writing", "chapter": n,
            "reason": f"第{n}章已从废章恢复到正文，待确认", "at": _now(),
        }
        save_project(root, project)

    # 章回到正文索引：退稿时撤回的连续性状态与卷摘要跟着回来。
    try:
        from . import continuity, memory_gen

        continuity.reapply_chapter(root, n)
        memory_gen.restore_volume_memory(root, n)
    except Exception:  # noqa: BLE001 - 派生数据恢复失败不该让恢复失败
        pass
    return {"ok": True, "restored": n, "chapter": read_index_entry(root, n)}


# --------------------------------- 伏笔 ---------------------------------

FORESHADOW_FILE = "ledger/foreshadow.jsonl"


def add_foreshadow(
    root: str | os.PathLike,
    *,
    name: str,
    kind: str = "detail",
    planted_chapter: int = 0,
    due_chapter: int | None = None,
    reveal_who: str = "",
    hint: str = "",
) -> dict[str, Any]:
    """作者手动埋一条伏笔，直接落 ledger/foreshadow.jsonl。"""
    label = name.strip()
    if not label:
        raise ReviewError("伏笔名称不能为空")
    n = int(planted_chapter or 0)
    if n <= 0:
        raise ReviewError("埋设章必须是正整数")
    due = None if due_chapter in (None, "", 0) else int(due_chapter)
    if due is not None and due <= n:
        raise ReviewError("回收章必须晚于埋设章")
    kind = kind if kind in ("main", "volume", "detail") else "detail"

    with project_lock(root):
        _project(root)
        row = {
            "id": f"fs-{uuid.uuid4().hex[:8]}",
            "name": label,
            "kind": kind,
            "plantedChapter": n,
            "dueChapter": due,
            "status": "open",
            "source": "作者手动埋设",
            "revealWho": reveal_who.strip(),
            "hint": hint.strip(),
            "at": _now(),
        }
        append_jsonl(project_path(root, FORESHADOW_FILE), row)
        return row


def payoff_foreshadow(root: str | os.PathLike, fs_id: str, chapter: int) -> dict[str, Any]:
    """把一条伏笔标记为已回收；fold 时 op=payoff → status=paid。"""
    fid = fs_id.strip()
    if not fid:
        raise ReviewError("缺少伏笔 id")
    n = int(chapter or 0)
    if n <= 0:
        raise ReviewError("回收章必须是正整数")

    with project_lock(root):
        _project(root)
        rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
        current = next((r for r in rows if str(r.get("id")) == fid), None)
        if not current:
            raise ReviewError(f"没有这条伏笔：{fid}")
        if current.get("status") == "paid":
            raise ReviewError(f"「{current.get('name')}」已经收过了")
        append_jsonl(project_path(root, FORESHADOW_FILE), {
            "op": "payoff",
            "id": fid,
            "payoffChapter": n,
            "at": _now(),
        })
        return {"ok": True, "id": fid, "payoffChapter": n}


def abandon_foreshadow(root: str | os.PathLike, fs_id: str, note: str = "") -> dict[str, Any]:
    """明确放弃一条伏笔：fold 时 op=abandon → status=abandoned，体检不再追。

    放弃不删账：原记录留在 jsonl 里，只有一条放弃事件追加在后面。
    """
    fid = fs_id.strip()
    if not fid:
        raise ReviewError("缺少伏笔 id")

    with project_lock(root):
        _project(root)
        rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
        current = next((r for r in rows if str(r.get("id")) == fid), None)
        if not current:
            raise ReviewError(f"没有这条伏笔：{fid}")
        if current.get("status") == "paid":
            raise ReviewError(f"「{current.get('name')}」已经收过了，不能放弃")
        if current.get("status") == "abandoned":
            raise ReviewError(f"「{current.get('name')}」已经放弃过了")
        append_jsonl(project_path(root, FORESHADOW_FILE), {
            "op": "abandon",
            "id": fid,
            "note": note.strip(),
            "at": _now(),
        })
        return {"ok": True, "id": fid, "name": current.get("name"), "note": note.strip()}


# --------------------------------- 正文 ---------------------------------


def _entry_from_text(base: dict[str, Any], text: str) -> dict[str, Any]:
    m = text_metrics(text)
    tells = detect_ai_tells(text)
    level = verdict(m, tells)
    hook = check_chapter_end_hook(text)
    return {
        **base,
        "chars": m["chars"],
        "dialogueRatio": m["dialogueRatio"],
        "verdict": level["level"],
        "chapterVerdict": "needs_fix" if level["level"] == "差" else "pass",
        "aiTellDensity": level["density"],
        "endHook": hook,
        "fixReasons": [],
        "summary": base.get("summary") or clamp_summary(text, 240),
    }


def save_chapter_text(
    root: str | os.PathLike,
    number: int,
    text: str,
    *,
    title: str | None = None,
    unapprove: bool = True,
) -> dict[str, Any]:
    with project_lock(root):
        _project(root)
        n = int(number)
        entry = read_index_entry(root, n)
        if not entry:
            raise ChapterNotFound(f"没有第{n}章")
        clean = (text or "").strip()
        if not clean:
            raise ReviewError("正文不能为空")
        entry_title = (title or entry.get("title") or f"第{n}章").strip()
        _, rel = write_chapter(root, n, entry_title, clean)
        row = _entry_from_text({**entry, "number": n, "title": entry_title, "file": rel}, clean)
        if unapprove:
            row["approved"] = False
            row["approvedAt"] = ""
        add_to_index(root, row)
        # 正文被整篇保存过：旧的一轮复检条目不再对应当前稿子。
        close_ai_round(root, n, "edit")
        return {"ok": True, "chapter": read_index_entry(root, n), "check": check_chapter(root, n)}


# --------------------------------- 上下文 ---------------------------------


def _stage_for(root: str | os.PathLike, n: int) -> dict[str, Any] | None:
    for seg in fold_segments(read_jsonl(project_path(root, SEGMENTS_FILE))):
        if int(seg.get("from") or 0) <= n <= int(seg.get("to") or 0):
            for stage in ((seg.get("plan") or {}).get("stages") or []):
                if n in [int(x) for x in (stage.get("chapters") or [])]:
                    return stage
    return None


def _skill_block(root: str | os.PathLike, skills: list[str]) -> str:
    """按技能加载提示词模块，逐块截断到 1600 字；缺失模块跳过，不影响改写。"""
    blocks: list[str] = []
    for skill in skills:
        module = _SKILL_MODULES.get(skill)
        if not module:
            continue  # styleSamples 直接用提示词里的样章
        try:
            text = prompt_lib.load(module, root=root).strip()
        except (prompt_lib.PromptNotFound, ValueError):
            continue
        if not text:
            continue
        label = _SKILL_LABELS.get(skill, skill)
        blocks.append(f"【技能：{label}】\n{text[:_SKILL_MODULE_MAX_CHARS]}")
    return "\n\n".join(blocks)


def _rewrite_issues(check: dict[str, Any], extra: list[dict[str, Any]] | None = None) -> str:
    """改写要求里「必须改掉的问题」：后面重跑的确定性体检 + 前端带来的复检条目。

    两边的 message 可能重复（AI 复检会合并确定性结果），按 message 去重，
    最多 16 条，保证提示词不被问题清单淹没。
    """
    lines: list[str] = []
    seen: set[str] = set()
    for f in check.get("findings") or []:
        severity = str(f.get("severity") or "")
        message = str(f.get("message") or "").strip()
        if severity not in ("high", "mid") or not message or message in seen:
            continue
        seen.add(message)
        hint = str(f.get("hint") or "").strip()
        lines.append(f"- [{severity}] {message[:220]}" + (f" —— {hint[:220]}" if hint else ""))
    for f in extra or []:
        severity = str(f.get("severity") or "mid")
        if severity not in ("high", "mid"):
            continue
        message = str(f.get("message") or "").strip()
        if not message or message in seen:
            continue
        seen.add(message)
        source = "复检" if str(f.get("source") or "") == "ai" else "体检"
        hint = str(f.get("hint") or "").strip()
        lines.append(
            f"- [{severity}·{source}] {message[:220]}" + (f" —— {hint[:220]}" if hint else "")
        )
    if not lines:
        return "（确定性体检没有硬伤，按下面作者的要求改）"
    return "\n".join(f"{i}. {line[2:]}" for i, line in enumerate(lines[:16], 1))


def _build_rewrite_messages(root: str | os.PathLike, n: int, entry: dict[str, Any], body: str,
                            note: str, instruction: str, check: dict[str, Any],
                            skills: list[str] | None = None,
                            findings: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    project = load_project(root) or {}
    bible = load_bible(root)
    index = read_index(root)

    prev_text = ""
    prev = next((c for c in index if int(c.get("number") or 0) == n - 1), None)
    if prev:
        try:
            prev_text = (read_chapter(root, n - 1) or "")[-700:]
        except FileNotFoundError:
            prev_text = ""

    stage = _stage_for(root, n) or {}
    involved = [str(x) for x in (entry.get("characters") or [])]
    if stage.get("cast"):
        involved += [str(x) for x in stage["cast"]]
    chars = []
    for c in bible.get("characters") or []:
        names = [str(c.get("name") or ""), *[str(a) for a in (c.get("aliases") or [])]]
        if any(x and x in involved for x in names) or len(chars) < 2:
            chars.append(
                f"- {c.get('name')}：想要「{c.get('want') or '—'}」；怕「{c.get('fear') or '—'}」；"
                f"说话「{c.get('voice') or '—'}」"
            )
        if len(chars) >= 6:
            break
    rules = []
    for r in bible.get("rules") or []:
        text = str(r.get("text") or r.get("name") or "").strip()
        if not text:
            continue
        forbidden = "、".join(str(x) for x in (r.get("forbiddenKeywords") or [])[:4])
        rules.append(f"- {text[:100]}" + (f"（禁用：{forbidden}）" if forbidden else ""))
        if len(rules) >= 10:
            break

    style = bible.get("style") or {}
    style_lines = []
    if style.get("notes"):
        style_lines.append(f"- 备注：{str(style['notes'])[:200]}")
    if style.get("pov") or style.get("tense"):
        style_lines.append(f"- 视角/时态：{style.get('pov') or '—'} / {style.get('tense') or '—'}")
    if style.get("banned"):
        style_lines.append(f"- 禁用表达：{'、'.join(str(x) for x in style['banned'][:12])}")
    sample = ""
    if isinstance(style.get("samples"), list) and style["samples"]:
        first = style["samples"][0]
        sample = str(first.get("text") if isinstance(first, dict) else first)[:300]

    issues = _rewrite_issues(check, findings)

    nuewen_block = ""
    if project.get("nuewen"):
        nuewen_block = f"""
【虐文原则（必须执行）】
{NUWEN_REVERSALS}
- 每个反转必须有因果链：性格 → 压力下的选择 → 代价落地；禁止天灾、巧合、降智硬转。
- 反转要咬合：一个人的结局要成为另一个人的压力源。
- 情绪用动作、停顿、重复细节承载，不写嚎哭式抒情和总结句。
"""
    user = f"""【作品】{project.get('title') or ''}｜{project.get('genre') or ''}｜{project.get('tone') or ''}
【一句话】{project.get('logline') or ''}

【平台打法（必须遵守）】
{platform_brief(project.get('platform'))}
{nuewen_block}
【本章】第{n}章 {entry.get('title') or ''}
【本章摘要】{entry.get('summary') or '—'}
【上一章结尾（只作衔接，不要复述）】
{prev_text or '（没有上一章）'}

【本台阶】
目标：{stage.get('goal') or '—'}
转折：{stage.get('turn') or '—'}
节奏：{stage.get('pace') or '—'}
现场：{'、'.join(str(x) for x in (stage.get('places') or [])) or '—'}

【人物】
{chr(10).join(chars) or '（未登记人物卡）'}

【规则】
{chr(10).join(rules) or '（无）'}

【文风】
{chr(10).join(style_lines) or '—'}
{('【文风样本】' + chr(10) + sample) if sample else ''}

【必须改掉的问题（逐条落实，改的时候保住原有情节事实）】
{issues}

【作者要求】
{note.strip() or '（没附具体要求，按上面的问题改）'}
{('补充要求：' + instruction.strip()) if instruction.strip() else ''}

【本次改写技能】
{'、'.join(_SKILL_LABELS.get(s, s) for s in (skills or [])) or '仅按上面的问题与平台打法改'}
{_skill_block(root, skills or [])}

【原稿】
{body}
"""
    system = (
        "你是这部连载小说的作者本人，按编辑意见修改本章。硬性约束："
        "1) 保留所有已经发生的情节事实、人物关系和信息揭示顺序；"
        "2) 不新增设定、不新增角色、不新增能力，不改变伏笔的埋/收章；"
        "3) 只改命中问题的段落，不整章推倒重来，不改变章末钩子的类型；"
        "4) 保持人物口吻和既有文风，不写总结句、不解释情绪、不堆形容词；"
        "5) 输出完整章节正文，不要标题、不要说明、不要 Markdown 代码块；"
        "6) 按【平台打法】控制字数、段落长度、对话比和章末钩子，平台禁忌不能碰。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _record_usage(root: str | os.PathLike, row: dict[str, Any]) -> None:
    append_jsonl(project_path(root, USAGE_FILE), {"at": _now(), **row})


def _auto_write_back(root: str | os.PathLike, chapter: int, *, force: bool = False) -> dict[str, Any]:
    """改写落盘后重算这一章的记忆；失败只报告，不影响改写结果。"""
    try:
        from . import memory_gen

        return memory_gen.auto_write_back(root, chapter, force=force)
    except Exception as e:  # noqa: BLE001 — 记忆是派生数据，不拖垮改写
        return {"ok": False, "error": str(e)}


def rewrite_chapter(
    root: str | os.PathLike,
    number: int,
    *,
    note: str = "",
    instruction: str = "",
    model: str | None = None,
    skills: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """按技能改写：只改命中段落，成功后旧稿进废章、新稿回待确认。

    ``skills=None`` 时用 ``check_chapter()["suggestedSkills"]``；显式传入时只认白名单内的 id。
    模型调用放在锁外：一次改写可能几十秒，不能把整本书的写操作堵住。
    落盘前在锁内重跑硬校验（<300 字 / 低于目标 75% / 撞规则），任一失败旧稿一个字都不动。
    """
    n = int(number)
    entry = read_index_entry(root, n)
    if not entry:
        raise ChapterNotFound(f"没有第{n}章")
    try:
        body = read_chapter(root, n) or ""
    except FileNotFoundError:
        body = ""
    if not body.strip():
        raise ReviewError(f"第{n}章没有正文，先写再改")
    check = check_chapter(root, n)

    if skills is None:
        selected = list(check.get("suggestedSkills") or [])
    else:
        selected = [s for s in skills if isinstance(s, str) and s in _REWRITE_SKILLS]
    selected = list(dict.fromkeys(selected))

    messages = _build_rewrite_messages(
        root, n, entry, body, note, instruction, check, selected, findings,
    )

    if on_stage:
        on_stage("按技能改写")
    result = chat(
        messages, model=model, temperature=0.5, max_tokens=12000, timeout=300, reasoning="low",
        on_delta=on_delta,
    )
    new_text = strip_fence(result["text"]).strip()
    lines = new_text.splitlines()
    if lines:
        head = lines[0].strip()
        if head == str(entry.get("title") or "").strip() or re.match(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章", head):
            new_text = "\n".join(lines[1:]).strip()

    with project_lock(root):
        project = _project(root)
        current = read_index_entry(root, n)
        if not current:
            raise ChapterConflict(f"第{n}章在改写期间被删除或退回，新稿没有落盘")

        # 落盘前守卫：不达标就停，旧稿与索引都不动，也不写废章。
        new_chars = count_chars(new_text)
        if new_chars < 300:
            raise ReviewError(f"模型返回的正文过短（{new_chars} 字，少于 300 字），旧稿未动")
        target = int(project.get("wordsPerChapter") or 0)
        if target > 0 and new_chars < target * 0.75:
            raise ReviewError(
                f"模型返回 {new_chars} 字，低于本章目标 {target} 字的 75%，旧稿未动"
            )
        hits = hard_rule_hits((load_bible(root).get("rules") or []), new_text)
        if hits:
            detail = "；".join(f"「{h['rule']}」{h['matched']}" for h in hits[:3])
            raise ReviewError(f"改写后撞规则：{detail}，旧稿未动")

        ensure_dir(project_path(root, LAYOUT["drafts"]))
        draft_name = f"{pad3(n)}-{_safe_name(current.get('title'), '未命名')}-rewrite-{int(datetime.now().timestamp() * 1000):x}.md"
        draft_rel = f"{LAYOUT['drafts']}/{draft_name}"
        Path(project_path(root, draft_rel)).write_text(body, encoding="utf-8")
        _, rel = write_chapter(root, n, current.get("title"), new_text)
        row = _entry_from_text({**current, "number": n, "file": rel}, new_text)
        row["approved"] = False
        row["approvedAt"] = ""
        row["rewrittenAt"] = _now()
        add_to_index(root, row)
        append_jsonl(project_path(root, REVIEW_FILE), {
            "kind": "rewrite",
            "number": n,
            "title": current.get("title") or "",
            "reason": note.strip() or "按体检问题改写",
            "draftFile": draft_rel,
            "model": result["model"],
            "skills": selected,
            "at": _now(),
        })
        _record_usage(root, {
            "kind": "rewrite",
            "chapter": n,
            "chars": new_chars,
            "tokens": int(result["usage"].get("total_tokens") or estimate_tokens(new_text)),
            "model": result["model"],
            "skills": selected,
        })
        after = check_chapter(root, n)
        out = {
            "ok": True,
            "chapter": read_index_entry(root, n),
            "text": new_text,
            "chars": new_chars,
            "model": result["model"],
            "check": after,
            "skills": selected,
            "aiTellsBefore": {
                "total": check["aiTells"]["total"],
                "level": check["aiTells"]["level"],
                "density": check["aiTells"]["density"],
            },
            "aiTellsAfter": {
                "total": after["aiTells"]["total"],
                "level": after["aiTells"]["level"],
                "density": after["aiTells"]["density"],
            },
            "oldChars": count_chars(body),
            "newChars": new_chars,
        }
        record_check(root, after)

    # 整章换稿：这一轮复检的条目是针对旧稿的，下一轮重新出题。
    close_ai_round(root, n, "rewrite")
    # 改写会动正文事实，记忆随之重算；模型调用放在锁外。
    out["memory"] = _auto_write_back(root, n, force=True)
    return out


# -------------------------------- 段落重写 -------------------------------- #


def _paragraph_chunks(body: str) -> list[tuple[int, str]]:
    """按空行切段，返回 (在 split 结果里的下标, 原文)。

    保留分隔符的下标是为了替换时原样拼回去：不把作者的单空行/双空行改写掉。
    """
    parts = re.split(r"(\n\s*\n)", body)
    return [(i, parts[i]) for i in range(0, len(parts), 2) if parts[i].strip()]


def _paragraph_index(body: str, quote: str) -> int:
    """复检原句落在第几段（1 起）；找不到返回 0。"""
    key = _compact(quote)
    if len(key) < 4:
        return 0
    for i, (_, text) in enumerate(_paragraph_chunks(body), 1):
        if key in _compact(text):
            return i
    return 0


def rewrite_paragraph(
    root: str | os.PathLike,
    number: int,
    paragraph: int,
    *,
    instruction: str = "",
    finding: dict[str, Any] | None = None,
    model: str | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """只重写体检/复检命中的那一段，改完直接验证原句是否消失。

    整章改写动的地方太多，改完再复检又可能换一批问题；段落重写把范围锁死在
    被点名的那一段：改完 quote 不在正文里，这条问题就算解决，不用再赌模型。
    """
    n = int(number)
    entry = read_index_entry(root, n)
    if not entry:
        raise ChapterNotFound(f"没有第{n}章")
    try:
        body = read_chapter(root, n) or ""
    except FileNotFoundError:
        body = ""
    if not body.strip():
        raise ReviewError(f"第{n}章没有正文，先写再改")

    chunks = _paragraph_chunks(body)
    k = int(paragraph)
    if k < 1 or k > len(chunks):
        raise ReviewError(f"第{n}章没有第{k}段（共 {len(chunks)} 段）")
    idx, old = chunks[k - 1]
    # 相邻段只取接缝处，不把整章塞进提示词。
    prev = chunks[k - 2][1].strip()[-240:] if k >= 2 else ""
    nxt = chunks[k][1].strip()[:240] if k < len(chunks) else ""

    found = finding or {}
    quote = str(found.get("quote") or "").strip()
    message = str(found.get("message") or "").strip()
    basis = str(found.get("basis") or "").strip()
    hint = str(found.get("hint") or "").strip()
    if quote and _paragraph_index(body, quote) not in (0, k):
        # 原句不在这一段：作者看的结果和正文对不上，先别乱改。
        raise ReviewError(f"这条问题的原句不在第 {k} 段，正文可能已经改过；重新体检后再试")

    project = load_project(root) or {}
    bible = load_bible(root)
    involved = [str(x) for x in (entry.get("characters") or [])]
    voices = []
    for c in bible.get("characters") or []:
        names = [str(c.get("name") or ""), *[str(a) for a in (c.get("aliases") or [])]]
        if involved and not any(x and x in involved for x in names):
            continue
        voices.append(f"- {c.get('name')}：想要「{c.get('want') or '—'}」；怕「{c.get('fear') or '—'}」；说话「{c.get('voice') or '—'}」")
        if len(voices) >= 5:
            break

    issue_lines = []
    if message:
        issue_lines.append(f"- [{found.get('severity') or 'mid'}] {message[:220]}")
    if quote:
        issue_lines.append(f"  原句（改完不能还在）：{quote[:160]}")
    if basis:
        issue_lines.append(f"  依据：{basis[:200]}")
    if hint:
        issue_lines.append(f"  改法：{hint[:220]}")
    issues = "\n".join(issue_lines) or "（没有具体问题，按作者要求改这一段）"

    prompt = f"""【作品】{project.get('title') or ''}｜{project.get('genre') or ''}
【本章】第{n}章 {entry.get('title') or ''}
【本章摘要】{entry.get('summary') or '—'}

【人物口吻】
{chr(10).join(voices) or '（未登记人物卡）'}

【上一段（只作衔接，不要重写）】
{prev or '（本章开头）'}

【要改的段落（第 {k} 段，共 {len(chunks)} 段）】
{old}

【下一段（只作衔接，不要重写）】
{nxt or '（本章结尾）'}

【这一段必须改掉的问题】
{issues}

【作者补充要求】
{instruction.strip() or '（没有补充，按上面的问题改这一段）'}

只输出改写后的第 {k} 段正文。硬性约束：
1) 不要章节标题、不要「第 k 段」这类标签、不要解释、不要 JSON、不要代码块；
2) 保留这一段里已经发生的事实、在场人物、时间地点、物品与伤势，信息揭示顺序不变；
3) 不新增设定、不新增角色、不新增能力；
4) 不改变前后段的事件与衔接，上一段怎么收、下一段怎么起都要接得上；
5) 字数与原文接近（30% 到 300% 之间），不写总结句、不解释情绪。
"""
    system = (
        "你是这部连载小说的作者本人，只改编辑点名的那一段。"
        "输出必须只有一段（或至多两小段）正文，不能带任何说明。"
    )
    def ask(extra: str = "", stream: bool = False) -> tuple[str, dict[str, Any]]:
        user = prompt if not extra else f"{prompt}\n\n【上一版不合格】{extra}"
        res = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model, temperature=0.4, max_tokens=3000, timeout=180, reasoning="low",
            on_delta=on_delta if stream else None,
        )
        text = strip_fence(res["text"]).strip()
        text = re.sub(r"^第\s*\d+\s*段\s*[：:]\s*", "", text).strip()
        return text, res

    if on_stage:
        on_stage(f"重写第 {k} 段")
    new_para, result = ask(stream=True)
    if not new_para:
        raise ReviewError("模型没有返回可用的段落，旧稿未动")
    tokens = int(result["usage"].get("total_tokens") or 0)
    # 模型常把被点名的那句“换个说法保留下来”。原句是判定依据，必须真的消失；
    # 给它一次明确的重写机会，还留着才放弃。
    if quote and _compact(quote) in _compact(new_para):
        if on_stage:
            on_stage("原句还在，再改一次")
        retry_text, retry = ask(
            f"你上一次仍然保留了这句必须改掉的原句：「{quote[:120]}」。"
            "这一句不能原样出现，改成别的写法或直接删掉；其余要求不变，只输出改写后的这一段。",
        )
        tokens += int(retry["usage"].get("total_tokens") or 0)
        if retry_text:
            new_para, result = retry_text, retry
    if not new_para:
        raise ReviewError("模型没有返回可用的段落，旧稿未动")

    old_len = count_chars(old)
    new_len = count_chars(new_para)
    if new_len < max(20, int(old_len * 0.3)):
        raise ReviewError(f"改写后这一段过短（{new_len} 字，原文 {old_len} 字），旧稿未动")
    if new_len > old_len * 3 + 100:
        raise ReviewError(f"改写后这一段过长（{new_len} 字，原文 {old_len} 字），旧稿未动")
    hits = hard_rule_hits((bible.get("rules") or []), new_para)
    if hits:
        detail = "；".join(f"「{h['rule']}」{h['matched']}" for h in hits[:3])
        raise ReviewError(f"改写后撞规则：{detail}，旧稿未动")
    if quote and _compact(quote) in _compact(new_para):
        raise ReviewError("改写后原句还在这一段里，问题没解决，旧稿未动")

    with project_lock(root):
        current = read_index_entry(root, n)
        if not current:
            raise ChapterConflict(f"第{n}章在改写期间被删除或退回，新稿没有落盘")
        current_body = read_chapter(root, n) or ""
        current_chunks = _paragraph_chunks(current_body)
        if len(current_chunks) < k:
            raise ChapterConflict(f"第{n}章正文在改写期间变了，段落号对不上，新稿没有落盘")
        cur_idx, cur_old = current_chunks[k - 1]
        if quote and _compact(quote) not in _compact(current_body):
            raise ChapterConflict("正文在改写期间已经改过，这条问题可能已解决；新稿没有落盘")
        parts = re.split(r"(\n\s*\n)", current_body)
        parts[cur_idx] = new_para
        new_body = "".join(parts)

        ensure_dir(project_path(root, LAYOUT["drafts"]))
        draft_name = (
            f"{pad3(n)}-{_safe_name(current.get('title'), '未命名')}"
            f"-para{k}-{int(datetime.now().timestamp() * 1000):x}.md"
        )
        draft_rel = f"{LAYOUT['drafts']}/{draft_name}"
        Path(project_path(root, draft_rel)).write_text(current_body, encoding="utf-8")
        _, rel = write_chapter(root, n, current.get("title"), new_body)
        row = _entry_from_text({**current, "number": n, "file": rel}, new_body)
        row["approved"] = False
        row["approvedAt"] = ""
        row["rewrittenAt"] = _now()
        add_to_index(root, row)
        append_jsonl(project_path(root, REVIEW_FILE), {
            "kind": "paragraph-rewrite",
            "number": n,
            "title": current.get("title") or "",
            "paragraph": k,
            "before": cur_old,
            "after": new_para,
            "problem": message,
            "quote": quote,
            "draftFile": draft_rel,
            "model": result["model"],
            "at": _now(),
        })
        _record_usage(root, {
            "kind": "paragraph-rewrite",
            "chapter": n,
            "chars": count_chars(new_body),
            "tokens": tokens or estimate_tokens(new_para),
            "model": result["model"],
        })
        after = check_chapter(root, n)
        resolved = (not quote) or (_compact(quote) not in _compact(new_body))
        out = {
            "ok": True,
            "number": n,
            "paragraph": k,
            "chapter": read_index_entry(root, n),
            "text": new_body,
            "oldParagraph": cur_old,
            "paragraphText": new_para,
            "chars": count_chars(new_body),
            "model": result["model"],
            "check": after,
            # 原句消失了才算解决；前端据此把这条问题从面板上摘掉。
            "resolved": resolved,
        }

    record_check(root, after)
    if resolved and message:
        # 这一条在复检轮次里记成已解决：下次点复检不会再冒出来。
        mark_ai_resolved(root, n, str(found.get("code") or ""), message, how="paragraph")
    return out


# --------------------------------- AI 复检 ---------------------------------


def _prev_chapter_tail(root: str | os.PathLike, n: int, limit: int = 600) -> str:
    """上一章结尾原文：跨章问题最常出在接缝上（时间、地点、伤势、手里拿的东西）。"""
    if n <= 1:
        return ""
    try:
        prev = read_chapter(root, n - 1) or ""
    except FileNotFoundError:
        return ""
    text = prev.strip()
    return text[-limit:] if text else ""


def _chapter_outline_brief(root: str | os.PathLike, n: int) -> str:
    """本章细纲要点：复检时对照「该写的写了没有、不该写的写了没有」。"""
    rows = read_jsonl(project_path(root, "ledger/outline.jsonl"))
    row: dict[str, Any] | None = None
    for item in rows:
        if not isinstance(item, dict) or int(item.get("chapter") or 0) != n:
            continue
        if item.get("deleted"):
            row = None
        else:
            row = item
    if not row:
        return ""
    lines: list[str] = []
    beats = [str(x).strip() for x in (row.get("beats") or []) if str(x).strip()]
    if beats:
        lines.append("节拍：" + "；".join(beats[:8]))
    for key, label in (("mustInclude", "必须出现"), ("mustAvoid", "必须回避")):
        values = [str(x).strip() for x in (row.get(key) or []) if str(x).strip()]
        if values:
            lines.append(f"{label}：" + "；".join(values[:8]))
    return "\n".join(lines)


def ai_check_chapter(
    root: str | os.PathLike,
    number: int,
    model: str | None = None,
    *,
    force: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_reason: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """模型复检一层语义问题（吃书、动机断裂、对话不贴人物），与确定性体检合并。

    带上「前情提要 + 上一章结尾 + 本章细纲」，跨章问题才有判断依据；
    on_reason 打开流式思考过程（模型支持 reasoning_content 时才有内容）。
    """
    n = int(number)
    entry = read_index_entry(root, n)
    if not entry:
        raise ChapterNotFound(f"没有第{n}章")
    try:
        body = read_chapter(root, n) or ""
    except FileNotFoundError:
        body = ""
    if not body.strip():
        raise ReviewError(f"第{n}章没有正文")

    if on_stage:
        on_stage("读正文与前情")
    base = check_chapter(root, n)
    bible = load_bible(root)
    echo = build_echo_memory(root, chapter=n, budget_chars=4800)
    prior = str(echo.get("text") or "").strip()
    prev_tail = _prev_chapter_tail(root, n)
    outline_brief = _chapter_outline_brief(root, n)

    if not force:
        # 这一章已经有一轮复检在进行：返回修完剩下的条目，不再重新出题。
        # 否则就会出现「改完一条，再查又冒出两条」——模型永远能再找到问题。
        carried = carried_ai_check(root, n)
        if carried is not None:
            if on_stage:
                left = sum(1 for f in carried.get("findings") or [] if f.get("source") == "ai")
                on_stage(f"继续本轮复检：还剩 {left} 条，不重新扫")
            return carried

    def char_brief(c: dict[str, Any]) -> str:
        aliases = [str(a).strip() for a in (c.get("aliases") or []) if str(a).strip()]
        alias = f"，别名：{'、'.join(aliases)}" if aliases else ""
        return f"{c.get('name')}{alias}（{c.get('role') or ''}）"

    chars = "；".join(char_brief(c) for c in (bible.get("characters") or [])[:12])
    rules = "；".join(
        str(r.get("text") or r.get("name") or "")[:80] for r in (bible.get("rules") or [])[:12]
    )
    project = load_project(root) or {}
    nuewen_block = ""
    if project.get("nuewen"):
        nuewen_block = f"""
【虐文原则（也按这个审）】
{NUWEN_REVERSALS}
"""
    prompt = f"""请以连载小说责任编辑的身份审第{n}章《{entry.get('title') or ''}》，只找真实问题，不夸。

【平台打法（审稿基准）】
{platform_brief(project.get('platform'))}
{nuewen_block}

【人物】{chars or '—'}
【规则】{rules or '—'}
【本章摘要】{entry.get('summary') or '—'}

【前情提要（跨章对照用：只判断本章有没有写错前文，不要求改前文）】
{prior or '—'}

【上一章结尾（接缝处最容易吃书）】
{prev_tail or '—'}

【本章细纲（写正文时应该照这个）】
{outline_brief or '—'}

【正文】
{body}

先写 100–250 字审稿思路：说明你对照了前情里的哪几处、本章哪一处最可疑（连续散文，不要小标题、不要分点）。
空一行，再输出 JSON 数组，不要代码块、不要额外解释。每项：
{{"severity":"high|mid","code":"continuity|motivation|voice|dialogue|repetition|emotion-summary","message":"问题是什么","quote":"本章正文原句（逐字复制，10–80 字）","basis":"依据：前情第几章的哪句 / 细纲哪条 / 本章何处","hint":"怎么改（不新增设定）"}}

【判定标准：只有满足下面任意一条，才算问题】
high（必须改）：
1. 与【前情提要】或【上一章结尾】的明确事实矛盾：时间、地点、在场人、伤势、物品持有人、谁知道什么；
2. 违反【本章细纲】：标为「必须出现」的拍没写，或写了「必须回避」的内容；
3. 本章内部前后自相矛盾；
4. 视角越界：限知视角写了该角色不可能知道的事。
mid（建议改，可改可不改）：
5. 动机缺口：与人物卡的 want/fear 明确冲突（不是「感觉不像」）；
6. 信息重复：同一信息在本章内重复两次以上，删掉不影响理解。

【以下一律不算问题，不报】
- 文风、节奏、句子长短、比喻、用词偏好；
- 留白、悬念、没解释的伏笔（只要没违反细纲）；
- 前文自己的问题；本章没写但「可能」会矛盾的地方（推测）；
- 无法逐字引用本章原句的问题（细纲缺失类除外，用 basis 逐字引用细纲条目）；
- 与本章无关的后续/结构建议；
- 同一根因换种说法重复报。

【证据要求】每条 quote 必须从【正文】逐字复制；给不出 quote 的，basis 必须逐字引用细纲条目，否则不要报。
最多 6 条，high 最多 3 条；同一段最多报 2 条（能一起改掉）。按上面的标准没有问题的，输出 []，不要为了凑数报风格问题。"""
    selected_model = model or str(load_settings()["fastModel"])
    context_hash = _ai_context_hash(prompt, selected_model)
    if on_stage:
        on_stage("模型复检（对照前情）")
    result = chat(
        [
            {"role": "system", "content": "你是严格的网文编辑。先写审稿思路，再输出可解析的 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        model=selected_model,
        temperature=0,
        # 复检要先写审稿思路再给 JSON；推理链会把额度吃光、正文一个字不剩。
        # 思考过程由提示词里的「审稿思路」提供，这里关掉原生推理，并留足输出额度。
        max_tokens=16000,
        timeout=300,
        reasoning="none",
        on_delta=on_delta,
        on_reason=on_reason,
    )
    raw = result["text"].strip()
    parsed = _parse_finding_array(raw)
    tokens = int(result["usage"].get("total_tokens") or estimate_tokens(body))
    if parsed is None:
        # 模型偶尔会带前导说明、包成对象或直接写坏 JSON。修一次比让作者重试省事。
        repair = chat(
            [
                {"role": "system", "content": "你是格式修复器，只输出可解析的 JSON 数组。"},
                {"role": "user", "content": (
                    "把下面的审稿结果整理成 JSON 数组，每项含 "
                    "severity(high|mid)、code(continuity|motivation|voice|dialogue|repetition|emotion-summary)、"
                    "message、quote（本章原句）、basis（依据）、hint。"
                    "原文里没有 quote/basis 的不要编造。只输出数组，不要解释、不要代码块。\n\n"
                    f"{raw[:8000]}"
                )},
            ],
            model=selected_model,
            temperature=0,
            max_tokens=4000,
            timeout=180,
            reasoning="none",
        )
        tokens += int(repair["usage"].get("total_tokens") or 0)
        parsed = _parse_finding_array(repair["text"])
    if parsed is None:
        raise LLMError("模型没有返回可解析的问题数组（已自动修复一次）")

    ai_findings, dropped = _grounded_ai_findings(parsed, body, outline_brief, n)
    ai_high = sum(1 for f in ai_findings if f["severity"] == "high")
    ai_mid = sum(1 for f in ai_findings if f["severity"] == "mid")
    standard = {
        "verdict": "fail" if ai_high else "minor" if ai_mid else "pass",
        "high": ai_high,
        "mid": ai_mid,
        "filtered": dropped,
        "note": "只认能逐字引用本章原句（或细纲条目）的问题；文风、节奏、留白、推测不计。",
    }

    if on_stage:
        on_stage("整理问题")
    seen = {(f["code"], f["message"]) for f in base["findings"]}
    merged = list(base["findings"]) + [f for f in ai_findings if (f["code"], f["message"]) not in seen]
    rank = {"high": 0, "mid": 1, "info": 2}
    merged.sort(key=lambda f: (rank.get(f["severity"], 3), str(f.get("code") or ""), str(f.get("message") or "")))

    buckets: dict[str, list[dict[str, Any]]] = {code: [] for code, _ in _AI_GROUPS}
    for finding in ai_findings:
        buckets[finding["group"]].append(finding)
    groups = [
        {"code": code, "label": label, "count": len(buckets[code]), "findings": buckets[code]}
        for code, label in _AI_GROUPS
    ]

    _record_usage(root, {
        "kind": "ai-check",
        "chapter": n,
        "chars": count_chars(body),
        "tokens": tokens,
        "model": result["model"],
    })
    payload = {
        "number": n,
        "pass": not any(f["severity"] == "high" for f in merged),
        "findings": merged,
        "groups": groups,
        # 按事先定好的标准给结论：没有硬伤就是通过，只有 mid 不必重写。
        "standard": standard,
        "canRewrite": True,
        "chars": base["chars"],
        "dialogueRatio": base["dialogueRatio"],
        "endHook": base["endHook"],
        "verdict": base["verdict"],
        # 语义复检回包也要带确定性那一层，前端才能继续显示分类与定位。
        "aiTells": base["aiTells"],
        "rules": base["rules"],
        "checkedAt": base["checkedAt"],
        "textHash": base["textHash"],
        "suggestedSkills": base["suggestedSkills"],
        "model": result["model"],
        # 这次复检对照了哪些跨章材料，前端显示「对照范围」。
        "context": {
            "priorChapters": int(echo.get("covered") or 0),
            "prevTail": bool(prev_tail),
            "outline": bool(outline_brief),
        },
        "thinking": _thinking_text(result, raw),
    }
    # 开一轮复检：之后点复检读到的是这一轮（修掉的会摘掉），不重新扫。
    round_id = f"r-{uuid.uuid4().hex[:8]}"
    record_ai_round(root, payload, context_hash, round_id)
    payload["round"] = round_id
    payload["carried"] = False
    return payload
