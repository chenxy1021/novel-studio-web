"""审阅写操作：存档、退回、废章、正文保存、确定性体检、AI 改写/复检。

这里所有写操作都落项目目录（chapters/index.json、drafts/、ledger/review.jsonl、
project.json），不依赖浏览器 localStorage；换机器打开同一本书，审阅状态还在。
"""

from __future__ import annotations

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
from .memory import append_memory, clamp_summary
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
    overdue = [
        f for f in fores
        if f.get("status") == "open" and f.get("dueChapter") not in (None, "")
        and int(f.get("dueChapter") or 0) <= end
    ]
    blocking: list[dict[str, Any]] = []
    if overdue:
        names = "、".join(str(f.get("name")) for f in overdue[:5])
        blocking.append({
            "severity": "mid",
            "code": "foreshadow-overdue",
            "message": f"{len(overdue)} 条伏笔已经到期：{names}",
            "hint": "在批尾存档前收掉，或明确放弃这条线",
        })
    return {"from": start, "to": end, "chapters": chapters, "blocking": blocking, "checkedAt": _now()}


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


def _build_rewrite_messages(root: str | os.PathLike, n: int, entry: dict[str, Any], body: str,
                            note: str, instruction: str, check: dict[str, Any],
                            skills: list[str] | None = None) -> list[dict[str, str]]:
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

    issues = "\n".join(
        f"{i}. [{f['severity']}] {f['message']}" + (f" —— {f['hint']}" if f.get("hint") else "")
        for i, f in enumerate(check.get("findings") or [], 1)
        if f["severity"] in ("high", "mid")
    ) or "（确定性体检没有硬伤，按下面作者的要求改）"

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

【必须改掉的问题】
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

    messages = _build_rewrite_messages(root, n, entry, body, note, instruction, check, selected)

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

    # 改写会动正文事实，记忆随之重算；模型调用放在锁外。
    out["memory"] = _auto_write_back(root, n, force=True)
    return out


# --------------------------------- AI 复检 ---------------------------------


def ai_check_chapter(root: str | os.PathLike, number: int, model: str | None = None) -> dict[str, Any]:
    """模型复检一层语义问题（吃书、动机断裂、对话不贴人物），与确定性体检合并。"""
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

    base = check_chapter(root, n)
    bible = load_bible(root)

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
【正文】
{body}

只输出 JSON 数组，不要解释。每项：
{{"severity":"high|mid","code":"continuity|motivation|voice|dialogue|repetition|emotion-summary","message":"问题是什么（具体到章内位置）","hint":"怎么改"}}
六类必须覆盖，code 只能取上面六个之一：
- continuity 吃书：与前面章节/设定矛盾
- motivation 动机：角色为什么此刻做，缺压力/代价
- voice 口吻：说话不像人物卡
- dialogue 对话：对话不推进、信息重复、说明式台词
- repetition 信息重复：同一信息换说法反复说
- emotion-summary 情绪总结：用总结句代替动作/细节
最多 12 条。high 只给会让读者出戏或吃书的硬伤；没有就输出 []。"""
    result = chat(
        [
            {"role": "system", "content": "你是严格的网文编辑，只输出可解析的 JSON 数组。"},
            {"role": "user", "content": prompt},
        ],
        model=model or str(load_settings()["fastModel"]),
        temperature=0.2,
        max_tokens=6000,
        timeout=240,
        reasoning="none",
    )
    raw = result["text"].strip()
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        raise LLMError("模型没有返回可解析的 JSON 数组")
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"模型返回的 JSON 解析失败：{e}") from e
    if not isinstance(parsed, list):
        raise LLMError("模型返回的不是 JSON 数组")

    ai_findings: list[dict[str, Any]] = []
    for item in parsed[:12]:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        code = str(item.get("code") or "ai-review")[:40]
        ai_findings.append({
            "severity": _severity(item.get("severity")),
            "code": code,
            "group": _group_of(code),
            "message": message[:300],
            "hint": str(item.get("hint") or "")[:300],
            "chapter": n,
            "source": "ai",
        })

    seen = {(f["code"], f["message"]) for f in base["findings"]}
    merged = list(base["findings"]) + [f for f in ai_findings if (f["code"], f["message"]) not in seen]
    rank = {"high": 0, "mid": 1, "info": 2}
    merged.sort(key=lambda f: rank.get(f["severity"], 3))

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
        "tokens": int(result["usage"].get("total_tokens") or estimate_tokens(body)),
        "model": result["model"],
    })
    return {
        "number": n,
        "pass": not any(f["severity"] == "high" for f in merged),
        "findings": merged,
        "groups": groups,
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
    }
