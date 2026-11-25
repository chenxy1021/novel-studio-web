"""审阅写操作：存档、退回、废章、正文保存、确定性体检、AI 改写/复检。

这里所有写操作都落项目目录（chapters/index.json、drafts/、ledger/review.jsonl、
project.json），不依赖浏览器 localStorage；换机器打开同一本书，审阅状态还在。
"""

from __future__ import annotations

import hashlib
import json
import logging
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
from .foreshadow_gen import _name_key, _name_taken
from .memory import append_memory, build_echo_memory, character_state, clamp_summary, load_memory_rows
from .metrics import (
    AI_TELL_HINTS,
    METRICS_VERSION,
    check_chapter_end_hook,
    count_chars,
    detect_ai_tells,
    estimate_tokens,
    paragraph_spans,
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
AI_CHECK_VERSION = "2026-11-25.4"
REVIEW_FILE = "ledger/review.jsonl"
USAGE_FILE = "metrics/usage.jsonl"
SEGMENTS_FILE = "ledger/segments.jsonl"

logger = logging.getLogger("novel.review")


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


def _lenient_json(raw: str) -> Any:
    """严格 JSON 解析失败时，去掉尾逗号再试一次；都不行返回 None。"""
    for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            return json.loads(attempt)
        except (TypeError, ValueError):
            continue
    return None


def _thinking_text(result: dict[str, Any], raw: str) -> str:
    """优先用模型的 reasoning_content；没有就取 JSON 前面的审稿思路。"""
    native = str(result.get("reason") or "").strip()
    if native:
        return native
    cuts = [pos for pos in (raw.find("{"), raw.find("[")) if pos > 0]
    preface = (raw[: min(cuts)] if cuts else "").strip()
    return preface[:4000]


def _compact(value: Any) -> str:
    return re.sub(r"[\s　]+", "", str(value or ""))


def _dismissed(root: str | os.PathLike, chapter: int) -> list[dict[str, Any]]:
    """这一章作者点过「忽略」的确定性体检条目。"""
    out: list[dict[str, Any]] = []
    for row in read_jsonl(project_path(root, CHECKS_FILE)):
        if not isinstance(row, dict) or row.get("__corrupt"):
            continue
        if row.get("kind") != "check-dismiss":
            continue
        try:
            ch = int(row.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if ch == int(chapter):
            out.append(row)
    return out


def _sample_dismissed(dismissed: list[dict[str, Any]], code: str, sample: dict[str, Any]) -> bool:
    """同一条命中句被忽略过：按原句认，原句空时退回行号 + 行内偏移。"""
    text = _compact(sample.get("text"))
    line, offset = int(sample.get("line") or 0), int(sample.get("offset") or -1)
    for row in dismissed:
        if str(row.get("code") or "") != code:
            continue
        quote = _compact(row.get("quote"))
        if quote and text:
            if quote == text:
                return True
            continue
        if int(row.get("line") or 0) == line and int(row.get("offset") or -2) == offset:
            return True
    return False


def _finding_dismissed(dismissed: list[dict[str, Any]], finding: dict[str, Any]) -> bool:
    """没有原句的确定性条目（平台格式、撞规则、章尾等）按代码 + 原消息认。"""
    code = str(finding.get("code") or "")
    message = _compact(finding.get("message"))
    for row in dismissed:
        if str(row.get("code") or "") != code:
            continue
        quote = _compact(row.get("quote"))
        if quote and quote == message:
            return True
        if not quote and _compact(row.get("message")) == message:
            return True
    return False


def _target_chars(project: dict[str, Any], rules: dict[str, Any]) -> int:
    """单章目标字数：书级 wordsPerChapter 优先，其次平台下限。"""
    return int(project.get("wordsPerChapter") or 0) or int(rules.get("wordsMin") or 0)


def _rewrite_floor(project: dict[str, Any]) -> tuple[int, int]:
    """改写后这一章能接受的字数底线，以及书级硬下限：(底线, 硬下限)。

    底线就是硬下限：改写也要守住「每章不少于 1800」这条，不能改完还是不够存档。
    短篇书（≤50 章）没设硬下限时退回「目标的 75%」，与原来的口径一致。
    """
    hard = chapter_min_chars(project)
    if hard:
        return hard, hard
    return int(_target_chars(project, platform_rules(project.get("platform"))) * 0.75), 0


def _ai_tells_payload(body: str, tells: list[dict[str, Any]], level: dict[str, Any]) -> dict[str, Any]:
    """确定性 AI 痕迹的结构化结果：分类、样例、定位，供体检面板直接渲染。"""
    categories = []
    for tell in tells:
        categories.append({
            "id": tell["id"],
            "label": tell["label"],
            "severity": tell["severity"],
            "hint": AI_TELL_HINTS.get(str(tell["id"]), ""),
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
    dismissed = _dismissed(root, n)
    kept: list[dict[str, Any]] = []
    for hit in tells:
        code = f"ai-tell-{hit['id']}"
        samples, dropped = [], 0
        for sample in hit.get("samples") or []:
            if _sample_dismissed(dismissed, code, sample):
                dropped += 1
            else:
                samples.append(sample)
        if dropped:
            hit = {**hit, "count": max(0, int(hit.get("count") or 0) - dropped), "samples": samples}
        if int(hit.get("count") or 0) > 0:
            kept.append(hit)
    tells = kept
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
    findings = [f for f in findings if not _finding_dismissed(dismissed, f)]
    findings.sort(key=lambda f: rank.get(f["severity"], 3))

    # RuleChip 行：字数 / 对话比 / 章尾钩子 / 规则 / 平台格式。
    rules_out: list[dict[str, Any]] = []
    target = _target_chars(project, prules)
    min_chars = chapter_min_chars(project)
    if target > 0:
        soft_lo = int(round(target * 0.75))
        lo, hi = max(soft_lo, min_chars), max(int(round(target * 1.2)), max(soft_lo, min_chars))
        if m["chars"] < lo:
            # 硬下限比「目标的 75%」更严时，直接说硬下限：两块牌子说两套标准最费解。
            chars_msg = (
                f"{m['chars']} 字，低于每章硬下限 {min_chars} 字"
                if lo > soft_lo
                else f"{m['chars']} 字，低于目标 {target} 字的 75%（{lo} 字）"
            )
            chars_state = "bad"
        elif m["chars"] > hi:
            chars_state, chars_msg = "warn", f"{m['chars']} 字，超过目标 {target} 字的 120%（{hi} 字）"
        elif lo > soft_lo:
            chars_state, chars_msg = "ok", f"{m['chars']} 字，在 {lo}–{hi} 字之间（硬下限 {min_chars} 字）"
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
        "metricsVersion": METRICS_VERSION,
        "suggestedSkills": _suggest_skills(bible, tells, level, hook, hard, findings),
    }


def _ai_confirmed_payoff(root: str | os.PathLike, names: list[str], due: int, end: int) -> int:
    """AI 复检的清单里有一项「收这条线」且判过：正文已经写了，只差账本记收。

    重复录入的长短名字都要试：清单项通常只写基础名（「我儿子名字还在吗」），
    而账本里可能有带后缀的版本。按批体检据此自动记收，不再让作者手动点一遍。
    """
    keys = [_compact(n).lower() for n in names if len(_compact(n)) >= 4]
    if not keys:
        return 0
    for chapter in range(max(1, due), end + 1):
        active = active_ai_round(root, chapter)
        if not active:
            continue
        result = active["row"].get("result") or {}
        for check in result.get("checklist") or []:
            if not isinstance(check, dict) or check.get("state") != "pass":
                continue
            label = _compact(check.get("label")).lower()
            if "收" in label and any(key in label or label in key for key in keys):
                return chapter
    return 0


_PAYOFF_CACHE: dict[tuple[str, tuple[str, ...], str], dict[str, dict[str, Any]]] = {}
# 一章全文大概 2500–4000 字：截太短会把章末的收线（这条线通常压在后面）一起截掉。
_PAYOFF_CHAPTER_CHARS = 5000


def _payoff_verdicts(
    root: str | os.PathLike,
    lines: list[dict[str, Any]],
    lo: int,
    hi: int,
    model: str | None = None,
) -> dict[str, dict[str, Any]]:
    """对着这批正文核对：到期伏笔里哪几条其实已经写进正文了。

    返回 {uid: {"chapter": n, "evidence": "正文原句"}}。只认能在那一章正文里逐字找到的
    证据——模型说不出出处就当没收：按批体检会据此自动记收，不能靠脑补改账本。
    同样的清单 + 同样的正文不重复调用模型（点一次体检、标一条再体检都秒回）。
    """
    # 只看可能放着收线的那几章：最早到期章之前的不看，省掉一半提示词。
    dues = [int(line.get("dueChapter") or 0) for line in lines if int(line.get("dueChapter") or 0) > 0]
    first = max(1, lo, min(dues) if dues else lo)
    texts: dict[int, str] = {}
    for n in range(first, hi + 1):
        try:
            body = read_chapter(root, n) or ""
        except FileNotFoundError:
            continue
        if body.strip():
            texts[n] = body.strip()[:_PAYOFF_CHAPTER_CHARS]
    if not lines or not texts:
        return {}

    uids = tuple(str(line["uid"]) for line in lines)
    blocks: list[str] = []
    for i, line in enumerate(lines, 1):
        bits = [f"埋在第{line.get('plantedChapter')}章，计划第{line.get('dueChapter')}章收"]
        for key, label in (("plantBeat", "埋点"), ("hint", "中途提示"), ("revealChange", "揭开后")):
            value = str(line.get(key) or "").strip()
            if value:
                bits.append(f"{label}：{value[:120]}")
        blocks.append(f"{i}. id={line['uid']} {line.get('name')}\n   " + "；".join(bits))
    chapter_blocks = [
        f"=== 第{n}章 ===\n{texts[n]}"
        for n in sorted(texts)
    ]
    prompt = f"""你是连载小说的责任编辑。下面几章已经写完并存档。请对照正文核对：这些「到期伏笔」里，哪几条其实已经在正文里收回来了（被揭开、被兑现、被人当面说破）。

【伏笔清单】
{chr(10).join(blocks)}

【正文】
{chr(10).join(chapter_blocks)}

【怎么判】
- 伏笔名只是计划时的一句话，正文会用完全不同的说法写出来：按「这条线要交代的信息出现了没有」判，不按字面。
- 这条线的答案可能只有一两句话，也可能藏在别人的对话、一个动作或一个物件里；读者读完这几章能明白「原来如此」，就算收。
- 只认正文里明确写出来的：还在往前铺线索、只是提到相关物件、顺带写一句，都不算收。
- 拿不准就判没收，不要脑补；宁可漏判，也不要错记。
- collected 为 true 时，evidence 必须从【正文】逐字复制 8–40 字，就是证明它已经收了的那一句；chapter 写这句话在第几章。

只输出一个 JSON 对象，不要代码块：
{{"items":[{{"id":"清单里的 id","collected":true,"chapter":51,"evidence":"正文原句"}}]}}
清单里每一项都要出现一次；没收的写 {{"id":"…","collected":false}}。"""

    key = (str(Path(root)), uids, hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16])
    if key in _PAYOFF_CACHE:
        return _PAYOFF_CACHE[key]

    selected_model = model or str(load_settings()["fastModel"])
    try:
        result = chat(
            [
                {"role": "system", "content": "你是严格的网文编辑。只输出可解析的 JSON 对象。"},
                {"role": "user", "content": prompt},
            ],
            model=selected_model,
            temperature=0,
            # 本地网关上的模型偶尔会先想一大段再开口：额度给足，否则正文一个字都剩不下。
            max_tokens=8000,
            # 核对是「顺手多看一眼」，网关不通时别把按批体检卡上几分钟。
            timeout=120,
            reasoning="none",
        )
    except Exception as exc:  # noqa: BLE001 - 核对失败不能把按批体检整批拖死
        logger.warning("按批体检核对伏笔失败：%s", exc)
        return {}

    parsed = _lenient_json(str(result.get("text") or "").strip())
    rows = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        logger.warning("按批体检核对伏笔：模型没返回 items")
        return {}

    known = {str(line["uid"]): line for line in lines}
    compact_texts = {n: _compact(t) for n, t in texts.items()}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        uid = str(row.get("id") or "").strip()
        if uid not in known or uid in out or row.get("collected") not in (True, "true", 1):
            continue
        line = known[uid]
        try:
            chapter = int(row.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if not (int(line.get("plantedChapter") or 1) <= chapter <= hi):
            continue
        evidence = str(row.get("evidence") or "").strip()
        evidence_key = _compact(evidence)
        if len(evidence_key) < 6 or evidence_key not in compact_texts.get(chapter, ""):
            # 引不出原句 = 没有出处。自动记账不能建在这种判断上。
            continue
        out[uid] = {"chapter": chapter, "evidence": evidence[:80]}
    if len(_PAYOFF_CACHE) > 32:  # 一本书改来改去会攒很多历史键：多到一定量就整批丢掉
        _PAYOFF_CACHE.clear()
    _PAYOFF_CACHE[key] = out
    return out


def check_batch(root: str | os.PathLike, frm: Any = None, to: Any = None,
                *, verify: bool = False) -> dict[str, Any]:
    """按批体检：逐章确定性检查 + 跨章提醒（到期伏笔）。

    ``verify=True`` 时多跑一次模型核对到期伏笔：正文里已经收了的，自动记进账本并从
    提醒里去掉。默认关（确定性体检要能用、能秒回），页面上的「按批体检」显式打开。
    """
    project = _project(root)
    index = read_index(root)
    if not index:
        return {"from": 0, "to": 0, "chapters": [], "blocking": [], "autoPaid": [], "checkedAt": _now()}

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
    # 「这一批」以按批体检的章为准：之后存档要等这批全过才回写设定。
    with project_lock(root):
        current = load_project(root) or project
        current["reviewBatch"] = {
            "chapters": [int(c["number"]) for c in rows],
            "from": start,
            "to": end,
            "at": _now(),
        }
        save_project(root, current)

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
        # 同一章埋、同一章收，名字只是长短不同（「五点四十就到了」/「…却从不进登记室」）
        # 是同一条线的重复录入。面板合成一行，标一次会一起收掉，避免作者点两遍。
        groups: list[dict[str, Any]] = []
        for f in overdue:
            key = _compact(f.get("name")).lower()
            hit = None
            for group in groups:
                head = group["rows"][0]
                same_span = (
                    int(head.get("plantedChapter") or 0) == int(f.get("plantedChapter") or 0)
                    and int(head.get("dueChapter") or 0) == int(f.get("dueChapter") or 0)
                )
                if same_span and len(key) >= 4 and (key in group["key"] or group["key"] in key):
                    hit = group
                    break
            if hit is None:
                groups.append({"key": key, "rows": [f]})
            else:
                hit["rows"].append(f)
                if len(key) > len(hit["key"]):
                    hit["key"] = key
        # 正文里已经收了的，不该再当到期账追：核对方式先看 AI 复检的收线项，
        # 再（verify 打开时）看模型对着正文逐条判。
        if verify:
            asking: list[dict[str, Any]] = []
            for group in groups:
                rep = max(group["rows"], key=lambda r: len(str(r.get("name") or "")))
                uid = str(rep.get("id") or "")
                if not uid:
                    continue
                head = group["rows"][0]
                asking.append({
                    "uid": uid,
                    "name": str(rep.get("name") or ""),
                    "plantedChapter": int(head.get("plantedChapter") or 0),
                    "dueChapter": int(head.get("dueChapter") or 0),
                    "plantBeat": str(head.get("plantBeat") or ""),
                    "hint": str(head.get("hint") or ""),
                    "revealChange": str(head.get("revealChange") or ""),
                })
            verdicts = _payoff_verdicts(root, asking, start, end)
        else:
            verdicts = {}
        items = []
        auto_paid: list[dict[str, Any]] = []
        for group in groups:
            rep = max(group["rows"], key=lambda r: len(str(r.get("name") or "")))
            uid = str(rep.get("id") or "")
            name = str(rep.get("name") or "")
            due = int(group["rows"][0].get("dueChapter") or 0)
            ids = [str(r.get("id") or "") for r in group["rows"] if r.get("id")]
            # 正文里已经写了的两种来源：本次模型核对（有原文证据）、这一章 AI 复检的收线项判过。
            verdict = verdicts.get(uid)
            ai_chapter = 0 if verdict else _ai_confirmed_payoff(
                root, [str(r.get("name") or "") for r in group["rows"]], due, end,
            )
            paid_chapter = int(verdict["chapter"]) if verdict else int(ai_chapter or 0)
            if paid_chapter:
                # 已经写了：记进账本，提醒自然消失。出处写进 note，作者回看得到。
                note = (
                    f"按批体检核对：第{paid_chapter}章「{verdict['evidence']}」"
                    if verdict else f"AI 复检：第{paid_chapter}章确认已收"
                )
                with project_lock(root):
                    # 锁里再看一眼：另一次体检可能已经把这条收掉了，别记两遍。
                    current = {
                        str(r.get("id")): r
                        for r in fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
                    }
                    for fid in ids:
                        row = current.get(fid)
                        if not row or row.get("status") != "open":
                            continue
                        append_jsonl(project_path(root, FORESHADOW_FILE), {
                            "op": "payoff",
                            "id": fid,
                            "payoffChapter": paid_chapter,
                            "note": note,
                            "at": _now(),
                        })
                auto_paid.append({
                    "name": name, "chapter": paid_chapter, "ids": ids,
                    "via": "text" if verdict else "ai-check",
                })
                continue
            items.append({
                "id": uid,
                # 合并显示的同一条线：标记一次，所有重复项一起处理。
                "ids": ids,
                "name": name,
                "kind": str(group["rows"][0].get("kind") or "detail"),
                "plantedChapter": int(group["rows"][0].get("plantedChapter") or 0),
                "dueChapter": due,
                "overdueBy": max(0, end - due),
                "duplicates": len(group["rows"]) - 1,
            })
        if items:
            names = "、".join(str(item["name"]) for item in items[:5])
            more = f" 等 {len(items)} 条" if len(items) > 5 else ""
            dup = sum(item["duplicates"] for item in items)
            blocking.append({
                "severity": "mid",
                "code": "foreshadow-overdue",
                "message": f"{len(items)} 条伏笔已经到期，账本还没记收：{names}{more}"
                           + (f"（含 {dup} 条重复录入，已合并显示）" if dup else ""),
                "hint": "正文里已经写了就点「标为已收」，把收线章记进账本；这条线不打算写了就点「放弃」。",
                "items": items,
            })
    else:
        auto_paid = []
    return {
        "from": start, "to": end, "chapters": chapters, "blocking": blocking,
        "autoPaid": auto_paid, "checkedAt": _now(),
    }


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
    try:
        body = read_chapter(root, chapter) or ""
    except FileNotFoundError:
        body = ""
    body_key = _compact(body)

    def quote_gone(f: dict[str, Any]) -> bool:
        """原句在正文里已经不存在 = 这条已经被改掉了，不用作者再点一次。"""
        key = _compact(f.get("quote"))
        return bool(key) and len(key) >= 4 and key not in body_key

    def keep(f: dict[str, Any]) -> bool:
        return _ai_finding_key(f) not in resolved and not quote_gone(f)

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
    # 本轮清单状态跟着正文走：未过项的引用原句没了，就显示「已解决」。
    kept_checks = {str(f.get("checkId")) for f in ai_findings if f.get("checkId")}
    checklist = []
    for check in stored.get("checklist") or []:
        if not isinstance(check, dict):
            continue
        state = str(check.get("state") or "skip")
        if str(check.get("id")) in kept_checks:
            state = "fail"
        elif state == "fail":
            state = "resolved"
        checklist.append({**check, "state": state})
    auto_resolved = sum(
        1 for f in stored_findings
        if f.get("source") == "ai"
        and _ai_finding_key(f) not in resolved
        and quote_gone(f)
    )
    standard = dict(stored.get("standard") or {})
    standard.update({
        "verdict": "fail" if high else "minor" if mid else "pass",
        "high": high,
        "mid": mid,
        "items": len(checklist),
        "passed": sum(1 for c in checklist if c.get("state") == "pass"),
        "failed": sum(1 for c in checklist if c.get("state") == "fail"),
        "skipped": sum(1 for c in checklist if c.get("state") == "skip"),
        "resolved": sum(1 for c in checklist if c.get("state") == "resolved"),
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
        "checklist": checklist,
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
        # 只数真的在本轮里、且被摘掉的条目（手动确认 + 原句已改没）。
        "resolvedCount": sum(
            1 for f in stored_findings
            if f.get("source") == "ai" and _ai_finding_key(f) in resolved
        ) + auto_resolved,
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


def dismiss_check(
    root: str | os.PathLike,
    chapter: int,
    code: str,
    *,
    message: str = "",
    quote: str = "",
    line: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    """作者确认这条确定性体检是误报：记一次忽略，之后重跑不再冒出来。

    只针对确定性层（AI 痕迹命中句、平台格式、撞规则等）；AI 复检条目走
    ``resolve_ai_finding``。忽略不删原记录，账本追加一行即可，正文不动。
    """
    n = int(chapter)
    label = str(code or "").strip()
    if n <= 0:
        raise ChapterNotFound(f"没有第{n}章")
    if not label:
        raise ReviewError("缺少要忽略的体检代码")
    with project_lock(root):
        if not read_index_entry(root, n):
            raise ChapterNotFound(f"没有第{n}章")
        append_jsonl(project_path(root, CHECKS_FILE), {
            "kind": "check-dismiss",
            "chapter": n,
            "code": label,
            "message": str(message or "")[:300],
            "quote": str(quote or "")[:160],
            "line": int(line or 0),
            "offset": int(offset or 0),
            "at": _now(),
        })
    return check_chapter(root, n)


def _ai_context_hash(prompt: str, model: str) -> str:
    """提示词里已经包含正文、前情、上一章结尾、细纲、人物与规则，哈希它就是全部输入。"""
    raw = f"{AI_CHECK_VERSION}\x1f{model}\x1f{prompt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_checks(root: str | os.PathLike) -> list[dict[str, Any]]:
    """每章取最近一次体检；正文改过就按当前稿重跑，旧问题不再挂着。"""
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
        stale = (
            text_hash(body) != str(row.get("textHash") or "")
            or str((row.get("result") or {}).get("metricsVersion") or "") != METRICS_VERSION
        )
        if stale:
            try:
                result = _fresh_check(root, chapter)
                stale = False
            except Exception:  # noqa: BLE001 - 体检失败退回旧结果，不让整页打不开
                result = row["result"]
        else:
            result = row["result"]
        out.append({
            "chapter": chapter,
            "at": str(row.get("at") or ""),
            "stale": stale,
            "result": result,
        })
    return out


def _fresh_check(root: str | os.PathLike, chapter: int) -> dict[str, Any]:
    """正文改过：重跑确定性体检并落账，改掉的问题自动从缓存里消失。"""
    result = check_chapter(root, chapter)
    record_check(root, result)
    return result


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

        # 模型没回写这一章时补一条摘要级记忆；已有详细记忆就不能盖掉 moves/items。
        if n not in load_memory_rows(root)["byChapter"]:
            append_memory(root, {
                "chapter": n,
                "title": entry.get("title") or "",
                "summary": clamp_summary(entry.get("summary") or "", 240),
                "events": [],
                "state": "",
                "characters": entry.get("characters") or [],
                "source": "index",
            })
        applied = _apply_batch_continuity(root, n)
        return {
            "ok": True,
            "approved": n,
            "nextChapter": next_chapter,
            "chapter": read_index_entry(root, n),
            "gate": project["gate"],
            "settingsApplied": applied,
        }


def _batch_chapters(root: str | os.PathLike, n: int) -> list[int]:
    """这一章所属的批次：优先用最近一次按批体检的章，其次段落纲，最后按单章。"""
    project = load_project(root) or {}
    batch = project.get("reviewBatch") or {}
    checked: list[int] = []
    for value in batch.get("chapters") or []:
        try:
            ch = int(value)
        except (TypeError, ValueError):
            continue
        if ch > 0:
            checked.append(ch)
    if n in checked:
        return checked
    for seg in fold_segments(read_jsonl(project_path(root, SEGMENTS_FILE))):
        frm, to = int(seg.get("from") or 0), int(seg.get("to") or 0)
        if frm and to and frm <= n <= to:
            return list(range(frm, to + 1))
    return [n]


def _apply_batch_continuity(root: str | os.PathLike, n: int) -> dict[str, int]:
    """本批全部存档后才把章记忆里的位置/转手/状态并进 bible。

    写正文时只落章记忆，不动设定：这一批还要改、还要退，先写进去会把设定带脏。
    最后一批中的最后一章存档时一次性回写；重复调用是按章去重的，幂等。
    """
    chapters = _batch_chapters(root, n)
    index = read_index(root)
    approved = {
        int(c.get("number") or 0)
        for c in index
        if c.get("approved") and int(c.get("number") or 0) > 0
    }
    if not all(ch in approved for ch in chapters):
        return {"moves": 0, "items": 0, "factions": 0, "places": 0}
    from .continuity import reapply_chapter

    total = {"moves": 0, "items": 0, "factions": 0, "places": 0}
    for ch in chapters:
        try:
            counts = reapply_chapter(root, ch)
        except Exception:  # noqa: BLE001 - 设定回写是派生数据，不能拖垮存档
            continue
        for key in total:
            total[key] += int(counts.get(key) or 0)
    return total


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
        rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
        key = _name_key(label)
        hit = next(
            (f for f in rows if f.get("status") == "open" and _name_taken(key, {_name_key(f.get("name"))})),
            None,
        )
        if hit:
            raise ReviewError(f"已有伏笔「{hit.get('name')}」，同名或近似的不再重复埋")
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


def payoff_foreshadow(root: str | os.PathLike, fs_id: str, chapter: int,
                      *, note: str = "") -> dict[str, Any]:
    """把一条伏笔标记为已回收；fold 时 op=payoff → status=paid。

    ``note`` 记来源：手动标收留空，按批体检核对出来的写明第几章原句，方便作者回看。
    """
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
            **({"note": note.strip()} if note.strip() else {}),
            "at": _now(),
        })
        return {"ok": True, "id": fid, "payoffChapter": n}


def reopen_foreshadow(root: str | os.PathLike, fs_id: str) -> dict[str, Any]:
    """把一条已收的伏笔改回未收：账本只追加一条 reopen，原事件都留着。

    按批体检自动记收偶尔会判错；能改回来，自动记账才敢开。
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
        if current.get("status") != "paid":
            raise ReviewError(f"「{current.get('name')}」还没收，不用重新打开")
        append_jsonl(project_path(root, FORESHADOW_FILE), {
            "op": "reopen",
            "id": fid,
            "at": _now(),
        })
        return {"ok": True, "id": fid, "name": current.get("name")}



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
                            findings: list[dict[str, Any]] | None = None,
                            length: dict[str, int] | None = None) -> list[dict[str, str]]:
    project = load_project(root) or {}
    bible = load_bible(root)

    # 跨章接缝：上一章怎么收、下一章怎么起。没有就整块不给（第 1 章、还没写的章），
    # 不拿占位符让模型当参考。
    prev_text = _prev_chapter_tail(root, n, limit=700)
    next_text = _next_chapter_head(root, n, limit=500)
    seam = ""
    if prev_text:
        seam += f"【上一章结尾（只作衔接，不要复述）】\n{prev_text}\n\n"
    if next_text:
        seam += f"【下一章开头（只作衔接，不要复述）】\n{next_text}\n\n"

    # 字数写进提示词：模型不知道这本书的硬下限，只按「改写」理解就会越改越短。
    length_block = ""
    if length:
        bits = [f"现在 {int(length.get('chars') or 0)} 字"]
        if length.get("hard"):
            bits.append(f"硬下限 {int(length['hard'])} 字（低于它不能存档）")
        if length.get("target"):
            bits.append(f"目标 {int(length['target'])} 字")
        if length.get("floor"):
            bits.append(f"改写后不得少于 {int(length['floor'])} 字")
        if length.get("hard") and int(length.get("chars") or 0) < int(length["hard"]):
            gap = int(length["hard"]) - int(length.get("chars") or 0)
            bits.append(f"这一章现在还差 {gap} 字才到硬下限，改写时补足")
        length_block = (
            "【本章字数】" + "；".join(bits) + "。\n"
            "改问题句时优先改写句子，不要整段删掉；情节有余量就补场景、动作、对话。\n\n"
        )

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
{seam}{length_block}【本台阶】
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
    落盘前在锁内重跑硬校验（<300 字 / 低于字数底线 / 撞规则），任一失败旧稿一个字都不动。
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

    project = _project(root)
    body_chars = count_chars(body)
    floor, hard = _rewrite_floor(project)
    target_chars = _target_chars(project, platform_rules(project.get("platform")))

    if skills is None:
        selected = list(check.get("suggestedSkills") or [])
    else:
        selected = [s for s in skills if isinstance(s, str) and s in _REWRITE_SKILLS]
    selected = list(dict.fromkeys(selected))

    messages = _build_rewrite_messages(
        root, n, entry, body, note, instruction, check, selected, findings,
        length={"chars": body_chars, "floor": floor, "hard": hard, "target": target_chars},
    )

    def clean(text: str) -> str:
        text = strip_fence(text).strip()
        lines = text.splitlines()
        if lines:
            head = lines[0].strip()
            if head == str(entry.get("title") or "").strip() or re.match(
                r"^第\s*[0-9一二三四五六七八九十百零]+\s*章", head
            ):
                text = "\n".join(lines[1:]).strip()
        return text

    if on_stage:
        on_stage("按技能改写")
    result = chat(
        messages, model=model, temperature=0.5, max_tokens=12000, timeout=300, reasoning="low",
        on_delta=on_delta,
    )
    new_text = clean(str(result.get("text") or ""))

    # 字数不够先补写一次：短稿落盘后体检照样打回，不如现在就让模型写足。
    # 只补一次，避免无限加长；补完还不到底线就在锁里拒绝落盘。
    new_chars = count_chars(new_text)
    if hard and new_chars < hard:
        want = max(hard, int(hard * 1.15))
        if on_stage:
            on_stage(f"正文偏短（{new_chars} 字），正在补写")
        longer = chat(
            messages + [
                {"role": "assistant", "content": new_text},
                {"role": "user", "content": (
                    f"上一版只有 {new_chars} 字，低于本章硬下限 {hard} 字"
                    + (f"（目标 {target_chars} 字）" if target_chars else "")
                    + "。保留所有已经发生的情节事实、人物口吻、章末钩子和伏笔的埋收位置，"
                    f"把这一章补足：补场景、动作、对话和具体细节，写到 {want} 字以上；"
                    "不要新增设定或情节转折，不要说明、不要标题、不要 Markdown。"
                )},
            ],
            model=model, temperature=0.5, max_tokens=14000, timeout=300, reasoning="low",
        )
        longer_text = clean(str(longer.get("text") or ""))
        if count_chars(longer_text) > new_chars:
            new_text, result = longer_text, longer

    with project_lock(root):
        project = _project(root)
        current = read_index_entry(root, n)
        if not current:
            raise ChapterConflict(f"第{n}章在改写期间被删除或退回，新稿没有落盘")

        # 落盘前守卫：不达标就停，旧稿与索引都不动，也不写废章。
        new_chars = count_chars(new_text)
        if new_chars < 300:
            raise ReviewError(f"模型返回的正文过短（{new_chars} 字，少于 300 字），旧稿未动")
        if floor and new_chars < floor:
            why = (
                f"低于本章硬下限 {hard} 字"
                if hard
                else f"低于本章目标 {target_chars} 字的 75%（{floor} 字）"
            )
            raise ReviewError(f"模型返回 {new_chars} 字，{why}，旧稿未动")
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


def _paragraph_chunks(body: str) -> list[tuple[int, int, str]]:
    """按体检同一套分段切正文，返回 (起, 止, 原文)。

    切法来自 metrics.paragraph_spans：空行分段；一块里只有单换行、每行都在
    单段上限内时一行一段。每章只按一次回车分段的稿子，不会再让整章变成
    「第 1 段」。起止都落在非空白字符上，替换时只动这一段，前后空行原样保留。
    """
    return [(start, end, body[start:end]) for start, end in paragraph_spans(body)]


def _paragraph_index(body: str, quote: str) -> int:
    """复检原句落在第几段（1 起）；找不到返回 0。"""
    key = _compact(quote)
    if len(key) < 4:
        return 0
    for i, (_, _, text) in enumerate(_paragraph_chunks(body), 1):
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
    _, _, old = chunks[k - 1]
    body_chars = count_chars(body)
    old_len = count_chars(old)
    # 相邻段只取接缝处，不把整章塞进提示词。
    prev = chunks[k - 2][2].strip()[-240:] if k >= 2 else ""
    nxt = chunks[k][2].strip()[:240] if k < len(chunks) else ""
    # 跨章接缝：上一章怎么收、下一章怎么起。没有上一章/下一章（第 1 章、还没写的章）
    # 就整块不给，别让模型对着占位符编。
    prev_chapter = _prev_chapter_tail(root, n, limit=320)
    next_chapter = _next_chapter_head(root, n, limit=320)

    found = finding or {}
    quote = str(found.get("quote") or "").strip()
    message = str(found.get("message") or "").strip()
    basis = str(found.get("basis") or "").strip()
    hint = str(found.get("hint") or "").strip()
    code = str(found.get("code") or "")
    # AI 痕迹的硬规则（不是A而是B、空气凝固…）按「这一类句式在这一段清零」验收：
    # 只把原句改个说法、同类句式还在，等于没改，复检还会再冒出来。
    tell_id = code[len("ai-tell-"):] if code.startswith("ai-tell-") else ""
    strict_tell = tell_id if (tell_id and found.get("severity") == "high") else ""

    def tell_count(text: str) -> int:
        if not strict_tell:
            return 0
        return next(
            (int(t.get("count") or 0) for t in detect_ai_tells(text) if t.get("id") == strict_tell),
            0,
        )

    def remaining(text: str) -> list[str]:
        left: list[str] = []
        if quote and _compact(quote) in _compact(text):
            left.append(f"原句还在：「{quote[:80]}」")
        count = tell_count(text)
        if count:
            left.append(f"「{message[:40] or strict_tell}」这一类句式还剩 {count} 处")
        return left

    if quote and _paragraph_index(body, quote) not in (0, k):
        # 原句不在这一段：作者看的结果和正文对不上，先别乱改。
        raise ReviewError(f"这条问题的原句不在第 {k} 段，正文可能已经改过；重新体检后再试")

    project = load_project(root) or {}
    bible = load_bible(root)
    # 改一段不能把一章改短：本章离字数底线还有多少余量，这一段最多只能缩这么多。
    floor, hard = _rewrite_floor(project)
    target_chars = _target_chars(project, platform_rules(project.get("platform")))
    slack = max(0, body_chars - floor) if floor else old_len
    min_para = max(20, int(old_len * 0.3), old_len - slack)
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

    seam = ""
    if prev_chapter:
        seam += f"【上一章结尾（只作衔接，不要照抄）】\n{prev_chapter}\n\n"
    if next_chapter:
        seam += f"【下一章开头（只作衔接，不要照抄）】\n{next_chapter}\n\n"

    prompt = f"""【作品】{project.get('title') or ''}｜{project.get('genre') or ''}
【本章】第{n}章 {entry.get('title') or ''}
【本章摘要】{entry.get('summary') or '—'}

{seam}【人物口吻】
{chr(10).join(voices) or '（未登记人物卡）'}

【上一段（只作衔接，不要重写）】
{prev or '（本章开头）'}

【字数】这一段现在 {old_len} 字；本章 {body_chars} 字（硬下限 {hard or '未设'} 字，目标 {target_chars or '未设'} 字）。
改写后这一段不能少于 {min_para} 字：问题句优先改写，不要整段删掉。

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
4) 不改变前后段、前后章的事件与衔接，上一段怎么收、下一段怎么起、上一章怎么收尾、下一章怎么起头都要接得上；
5) 字数与原文接近（不少于 {min_para} 字、不超过 {old_len * 3 + 100} 字），不写总结句、不解释情绪。
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
    # AI 痕迹硬规则还要求这一类句式在本段清零；顺手把段写短了，本章就会被改薄。
    # 给它一次明确的重写机会，还不行才放弃。
    new_len = count_chars(new_para)
    left = remaining(new_para)
    short = new_len < min_para
    if left or short:
        extra = "；".join(left)
        if short:
            extra = (extra + "；" if extra else "") + (
                f"这一段只有 {new_len} 字，至少要 {min_para} 字"
                f"（本章 {body_chars} 字，硬下限 {hard or target_chars} 字）"
            )
        if on_stage:
            on_stage("还没改干净，再改一次" if left else "写短了，再改一次")
        retry_text, retry = ask(
            "你上一次没有改干净：" + extra + "。"
            "必须全部改掉：原句不能原样出现，同类句式也不能换个说法留下；"
            "字数不够就把场景、动作、细节写足；其余要求不变，只输出改写后的这一段。",
        )
        tokens += int(retry["usage"].get("total_tokens") or 0)
        if retry_text:
            new_para, result = retry_text, retry
    if not new_para:
        raise ReviewError("模型没有返回可用的段落，旧稿未动")

    new_len = count_chars(new_para)
    if new_len < min_para:
        raise ReviewError(
            f"改写后这一段过短（{new_len} 字，至少要 {min_para} 字：本章 {body_chars} 字，"
            f"硬下限 {hard or target_chars} 字），旧稿未动"
        )
    if new_len > old_len * 3 + 100:
        raise ReviewError(f"改写后这一段过长（{new_len} 字，原文 {old_len} 字），旧稿未动")
    hits = hard_rule_hits((bible.get("rules") or []), new_para)
    if hits:
        detail = "；".join(f"「{h['rule']}」{h['matched']}" for h in hits[:3])
        raise ReviewError(f"改写后撞规则：{detail}，旧稿未动")
    left = remaining(new_para)
    if left:
        raise ReviewError("改写后还没改干净：" + "；".join(left) + "，旧稿未动")

    with project_lock(root):
        current = read_index_entry(root, n)
        if not current:
            raise ChapterConflict(f"第{n}章在改写期间被删除或退回，新稿没有落盘")
        current_body = read_chapter(root, n) or ""
        current_chunks = _paragraph_chunks(current_body)
        if len(current_chunks) < k:
            raise ChapterConflict(f"第{n}章正文在改写期间变了，段落号对不上，新稿没有落盘")
        cur_start, cur_end, cur_old = current_chunks[k - 1]
        if _compact(cur_old) != _compact(old):
            raise ChapterConflict(f"第{n}章正文在改写期间变了，段落号对不上，新稿没有落盘")
        if quote and _compact(quote) not in _compact(current_body):
            raise ChapterConflict("正文在改写期间已经改过，这条问题可能已解决；新稿没有落盘")
        new_body = current_body[:cur_start] + new_para + current_body[cur_end:]

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
        resolved = (
            ((not quote) or (_compact(quote) not in _compact(new_body)))
            and (not strict_tell or tell_count(new_para) == 0)
        )
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
    if resolved and message and not strict_tell:
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


def _next_chapter_head(root: str | os.PathLike, n: int, limit: int = 600) -> str:
    """下一章开头原文：改本章结尾那几段时，要接得上下一章怎么起。没有就返回空。"""
    try:
        nxt = read_chapter(root, n + 1) or ""
    except FileNotFoundError:
        return ""
    text = nxt.strip()
    if not text:
        return ""
    head = text[:limit]
    if len(text) > limit:
        # 尽量停在句子末尾：半句话当参考，模型容易把下一章的开头接错。
        cut = max(head.rfind("。"), head.rfind("！"), head.rfind("？"), head.rfind("”"))
        if cut >= limit // 2:
            head = head[: cut + 1]
    return head


def _chapter_outline_row(root: str | os.PathLike, n: int) -> dict[str, Any] | None:
    """本章细纲行；同章写了多条以最后一条未删除的为准。"""
    rows = read_jsonl(project_path(root, "ledger/outline.jsonl"))
    row: dict[str, Any] | None = None
    for item in rows:
        if not isinstance(item, dict) or int(item.get("chapter") or 0) != n:
            continue
        if item.get("deleted"):
            row = None
        else:
            row = item
    return row


def _chapter_outline_brief(root: str | os.PathLike, n: int) -> str:
    """本章细纲要点：复检时对照「该写的写了没有、不该写的写了没有」。"""
    row = _chapter_outline_row(root, n)
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


# 复检从「自由找问题」改成「按固定清单逐项判定」：清单有限、可复核，
# 清单外的问题只能作为不影响结论的建议。判定项上限防止清单本身膨胀。
_CHECK_MAX_OUTLINE = 4
_CHECK_MAX_STATE = 3
_CHECK_STATE_CHARS = 600
# 伏笔也进清单：本章该埋的、该收的都要在正文里落到实处，不能只靠按批体检事后追账。
_CHECK_MAX_FORESHADOW = 4


_CHECK_MAX_SETTING = 2  # 每类（物品/地点/势力）最多查两条
_CHECK_MAX_RULES = 8


def _setting_check_items(root: str | os.PathLike, body: str) -> list[dict[str, Any]]:
    """本章出现的物品/地点/势力，加上世界硬规则，逐条对设定。

    固定的东西都要查：正文提到某个东西，就得和设定页里写的对得上（来历、结构、立场），
    不能一章一个说法。只挑本章正文里真的出现过的设定，避免清单膨胀。
    """
    bible = load_bible(root)
    items: list[dict[str, Any]] = []
    checks = (
        ("物品", bible.get("items") or [], lambda e: e.get("origin") or e.get("appearance") or "",
         "出现的物品与设定一致"),
        ("地点", bible.get("locations") or [], lambda e: e.get("geo") or e.get("structure") or "",
         "出现的地点与设定一致"),
        ("势力", bible.get("factions") or [], lambda e: e.get("nature") or "",
         "出现的势力与设定一致"),
    )
    for kind, entries, brief_of, hint in checks:
        picked = 0
        for entry in entries:
            if picked >= _CHECK_MAX_SETTING:
                break
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            aliases = [str(a).strip() for a in (entry.get("aliases") or []) if str(a).strip()]
            if not any(token and token in body for token in [name, *aliases]):
                continue
            brief = str(brief_of(entry) or "").strip()
            items.append({
                "id": f"setting-{kind}-{picked}",
                "kind": "fact",
                "label": f"{kind}设定：{name[:20]}",
                "rule": f"本章{hint}「{name}」" + (f"：{brief[:150]}" if brief else "") + "。",
                "ref": f"{name}：{brief[:150]}" if brief else name,
                "code": "continuity",
            })
            picked += 1
    rules = [r for r in (bible.get("rules") or []) if str(r.get("name") or "").strip()]
    if rules:
        lines = [
            f"「{r.get('name')}」" + (f"：{str(r.get('judge') or r.get('cost') or '')[:60]}" if (r.get("judge") or r.get("cost")) else "")
            for r in rules[:_CHECK_MAX_RULES]
        ]
        items.append({
            "id": "world-rules",
            "kind": "fact",
            "label": "不违反世界硬规则",
            "rule": "本章没有违反下列世界硬规则（只判明确违背，违反请引正文原句）：\n" + "\n".join(lines),
            "ref": "；".join(str(r.get("name")) for r in rules[:_CHECK_MAX_RULES]),
            "code": "continuity",
        })
    return items


def _foreshadow_check_items(root: str | os.PathLike, n: int) -> list[dict[str, Any]]:
    """本章应埋 / 应收的伏笔，逐条变成复检清单项。

    只取未收的线；同一章埋的、收的各自最多 _CHECK_MAX_FORESHADOW 条，超出的留给按批体检。
    """
    rows = [r for r in fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
            if r.get("status") == "open"]
    due = [r for r in rows if int(r.get("dueChapter") or 0) == n]
    plant = [r for r in rows if int(r.get("plantedChapter") or 0) == n]
    items: list[dict[str, Any]] = []
    for i, f in enumerate(due[:_CHECK_MAX_FORESHADOW]):
        name = str(f.get("name") or "").strip()
        want = str(f.get("revealChange") or f.get("hint") or "").strip()
        items.append({
            "id": f"foreshadow-due-{i}",
            "kind": "foreshadow-due",
            "severity": "mid",
            "label": f"本章应收伏笔：{name[:24]}",
            "rule": (
                f"本章把伏笔「{name}」收回来了"
                + (f"：{want[:80]}" if want else "")
                + "。正文里要能读到这条线被兑现、被揭开或被人当面说破；只是顺带提一句、线索还在往前铺的不算。"
            ),
            "ref": name,
            "code": "continuity",
        })
    for i, f in enumerate(plant[:_CHECK_MAX_FORESHADOW]):
        name = str(f.get("name") or "").strip()
        beat = str(f.get("plantBeat") or "").strip()
        items.append({
            "id": f"foreshadow-plant-{i}",
            "kind": "foreshadow-plant",
            "severity": "mid",
            "label": f"本章应埋伏笔：{name[:24]}",
            "rule": f"本章埋下伏笔「{name}」" + (f"：{beat[:80]}" if beat else "") + "。正文里要出现这个细节。",
            "ref": name,
            "code": "continuity",
        })
    return items


def _checklist_items(
    root: str | os.PathLike,
    n: int,
    entry: dict[str, Any],
    prev_tail: str,
    body: str = "",
) -> list[dict[str, Any]]:
    """这一章要逐项判定的固定清单。

    来源都是硬事实：细纲的必须项/回避项、本章应埋/应收的伏笔、本章出现过的设定与世界硬规则、
    上一章之前的人物状态、章内一致与视角。每一项都必须能回答「正文里有没有明确反证」，
    答不上来就是通过。
    """
    items: list[dict[str, Any]] = []
    row = _chapter_outline_row(root, n) or {}
    must_include = [str(x).strip() for x in (row.get("mustInclude") or []) if str(x).strip()]
    must_avoid = [str(x).strip() for x in (row.get("mustAvoid") or []) if str(x).strip()]
    for i, text in enumerate(must_include[:_CHECK_MAX_OUTLINE]):
        items.append({
            "id": f"outline-include-{i}",
            "kind": "include",
            "label": f"细纲必须出现：{text[:36]}",
            "rule": f"细纲标为「必须出现」的内容「{text}」在本章正文里出现了（同义改写也算）。",
            "ref": text,
            "code": "continuity",
        })
    for i, text in enumerate(must_avoid[:_CHECK_MAX_OUTLINE]):
        items.append({
            "id": f"outline-avoid-{i}",
            "kind": "avoid",
            "label": f"细纲必须回避：{text[:36]}",
            "rule": f"本章没有写细纲标为「必须回避」的内容「{text}」（同义、暗示都算写了）。",
            "ref": text,
            "code": "continuity",
        })
    items.extend(_foreshadow_check_items(root, n))

    names = [str(x).strip() for x in (entry.get("characters") or []) if str(x).strip()]
    for i, name in enumerate(names[:_CHECK_MAX_STATE]):
        state = character_state(root, chapter=n, names=[name])
        text = str(state.get("text") or "").strip()
        if not text:
            continue
        items.append({
            "id": f"state-{i}",
            "kind": "fact",
            "label": f"前情事实：{name}",
            "rule": "本章与下列前情事实不矛盾（人物在第几章知道了什么、和谁是什么关系）：\n"
                    + text[:_CHECK_STATE_CHARS],
            "ref": text[:_CHECK_STATE_CHARS],
            "code": "continuity",
        })

    if body:
        items.extend(_setting_check_items(root, body))

    if prev_tail:
        items.append({
            "id": "seam",
            "kind": "fact",
            "label": "衔接上一章结尾",
            "rule": "本章开头与【上一章结尾】在时间、地点、在场人、伤势、物品上接得上。",
            "ref": prev_tail[-240:],
            "code": "continuity",
        })
    items.append({
        "id": "internal",
        "kind": "internal",
        "label": "本章前后一致",
        "rule": "本章内部的时间、地点、人物位置、物品、伤势前后一致。",
        "ref": "",
        "code": "continuity",
    })
    items.append({
        "id": "pov",
        "kind": "pov",
        "label": "限知视角不越界",
        "rule": "只写视角人物能看到、听到、想到、推断出的内容，没有直接写进别人的内心。",
        "ref": "",
        "code": "continuity",
    })
    return items


def _check_item_id(raw: Any) -> str:
    """模型爱改大小写或把连字符写成下划线；归一化后再对清单。"""
    text = str(raw or "").strip().lower().replace("_", "-").replace("：", "-").replace(":", "-")
    return re.sub(r"[\s　]+", "", text)


def _checklist_from(parsed: Any) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("checks", "verdicts", "judgements", "judgments"):
        if isinstance(parsed.get(key), list):
            return {
                "checks": parsed[key],
                "suggestions": parsed.get("suggestions") if isinstance(parsed.get("suggestions"), list) else [],
            }
    return None


def _parse_checklist(raw: Any) -> dict[str, Any] | None:
    """从模型输出里抠出 {"checks": [...], "suggestions": [...]}；抠不出返回 None。"""
    text = strip_fence(str(raw or "")).strip()
    if not text:
        return None
    found = _checklist_from(_lenient_json(text))
    if found:
        return found
    # 前面的审稿思路可能带花括号；从每个 { 起都试着解析一次。
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        parsed = None
        try:
            parsed, _ = decoder.raw_decode(text[i:])
        except (TypeError, ValueError):
            end = text.rfind("}")
            if end > i:
                parsed = _lenient_json(text[i: end + 1])
        found = _checklist_from(parsed)
        if found:
            return found
    return None


def _is_pass(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("true", "pass", "passed", "ok", "yes"):
        return True
    # 「未通过 / 不通过」里的「通过」不能被当成 pass。
    if "不" in text or "未" in text or "fail" in text or "false" in text:
        return False
    return text in ("通过", "没问题")


def _checklist_findings(
    rows: list[Any],
    items: list[dict[str, Any]],
    body: str,
    n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """把逐项判定变成硬伤：只有判定 fail 且拿得出反证的项才算问题。"""
    by_id = {_check_item_id(item["id"]): item for item in items}
    body_key = _compact(body)
    judged: dict[str, bool] = {}
    out: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = by_id.get(_check_item_id(row.get("id")))
        if not item or item["id"] in judged:
            continue
        if _is_pass(row.get("pass")):
            judged[item["id"]] = True
            continue
        quote = str(row.get("quote") or "").strip()
        note = str(row.get("note") or "").strip()
        hint = str(row.get("hint") or "").strip()
        quote_key = _compact(quote)
        grounded = len(quote_key) >= 4 and quote_key in body_key
        # 「要求出现」和「该埋/该收的伏笔」是缺席型判定：没写就是没写，本来就没有原句可引。
        absence = item["kind"] in ("include", "foreshadow-due", "foreshadow-plant")
        if not absence and not grounded:
            # 说没过、却指不出正文哪一句：按「拿不准」处理，不逼作者改。
            dropped += 1
            continue
        judged[item["id"]] = False
        paragraph = _paragraph_index(body, quote)
        out.append({
            "severity": item.get("severity") or "high",
            "code": item["code"],
            "group": _group_of(item["code"]),
            "message": _check_message(item, note)[:300],
            "quote": "" if absence else quote[:160],
            "basis": (f"细纲：{item['ref']}" if item["kind"] in ("include", "avoid") else item["ref"])[:200],
            "hint": hint[:300],
            "paragraph": paragraph,
            "chapter": n,
            "source": "ai",
            # 前端靠它把「未过项」和具体问题对应起来；轮次刷新时也用它重算清单状态。
            "checkId": item["id"],
        })

    checklist = []
    for item in items:
        if item["id"] in judged:
            state = "pass" if judged[item["id"]] else "fail"
        else:
            state = "skip"
        checklist.append({"id": item["id"], "label": item["label"], "state": state})
    return out, checklist, dropped


def _check_message(item: dict[str, Any], note: str) -> str:
    kind = item["kind"]
    ref = item.get("ref") or item.get("label") or ""
    if kind == "include":
        return f"细纲要求出现但没写：{ref}" + (f"（{note}）" if note else "")
    if kind == "avoid":
        return f"细纲要求回避却写了：{ref}" + (f"（{note}）" if note else "")
    if kind == "foreshadow-due":
        return f"伏笔到期没收：{ref}" + (f"（{note}）" if note else "")
    if kind == "foreshadow-plant":
        return f"伏笔没埋下：{ref}" + (f"（{note}）" if note else "")
    if kind == "fact":
        return f"{item['label']}：{note or '与本章内容对不上'}"
    if kind == "pov":
        return f"视角越界：{note or '写了视角人物不可能知道的事'}"
    return f"本章前后矛盾：{note or '前后对不上'}"


_AI_MAX_SUGGESTIONS = 2


def _grounded_ai_suggestions(
    parsed: list[Any], body: str, n: int,
) -> tuple[list[dict[str, Any]], int]:
    """清单外的可选建议：只收动机/信息重复两类，必须引原句，且不影响结论。"""
    body_key = _compact(body)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for item in parsed:
        if not isinstance(item, dict) or len(out) >= _AI_MAX_SUGGESTIONS:
            dropped += 1
            continue
        quote = str(item.get("quote") or "").strip()
        quote_key = _compact(quote)
        if len(quote_key) < 4 or quote_key not in body_key:
            dropped += 1
            continue
        group = _group_of(item.get("code") or "motivation")
        if group not in ("motivation", "repetition"):
            dropped += 1
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            dropped += 1
            continue
        key = (group, _compact(message))
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append({
            "severity": "mid",
            "code": group,
            "group": group,
            "message": message[:300],
            "quote": quote[:160],
            "basis": str(item.get("basis") or "")[:200],
            "hint": str(item.get("hint") or "")[:300],
            "paragraph": _paragraph_index(body, quote),
            "chapter": n,
            "source": "ai",
        })
    return out, dropped


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
    items = _checklist_items(root, n, entry, prev_tail, body)
    checklist_prompt = json.dumps(
        [{"id": item["id"], "要求": item["rule"]} for item in items],
        ensure_ascii=False,
        indent=1,
    )
    prompt = f"""你是连载小说的责任编辑。这次不做开放式的「找问题」，只对照下面的固定清单逐项判定第{n}章《{entry.get('title') or ''}》。

【平台打法（判定基准）】
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

【判定清单（只判这些，id 原样返回，不要增删）】
{checklist_prompt}

【怎么判】
- 默认通过。只有正文里有明确反证、你能逐字引用出来时才判 fail；拿不准、需要推测、只是「感觉可以更好」，一律 pass。
- fail 必须给 quote：从【正文】逐字复制 10–80 字，能直接反驳这一项。
- 唯一例外：id 以 outline-include 开头的项是「要求出现」。正文没写就是 fail，quote 留空，note 写清楚缺了什么。
- note 一句话说明反证；hint 一句话给改法（不新增设定）。pass 的项 quote/note/hint 都留空。
- 清单外的问题一律不进 checks。最多放 1–2 条 suggestions（只收 motivation 动机缺口 / repetition 信息重复），必须引本章原句；suggestions 只是可选建议，不影响结论。
- 全部通过就全部 pass。不要为了显得认真而判 fail；文风、节奏、留白、用词偏好、后续建议都不算。

先写 100–250 字审稿思路：逐项说明你怎么判的（连续散文，不要小标题、不要分点）。
空一行，再输出一个 JSON 对象，不要代码块、不要额外解释：
{{"checks":[{{"id":"清单 id","pass":true,"quote":"","note":"","hint":""}}],"suggestions":[{{"severity":"mid","code":"motivation|repetition","message":"","quote":"","basis":"","hint":""}}]}}"""
    selected_model = model or str(load_settings()["fastModel"])
    context_hash = _ai_context_hash(prompt, selected_model)
    if on_stage:
        on_stage(f"模型逐项复检（{len(items)} 项）")
    result = chat(
        [
            {"role": "system", "content": "你是严格的网文编辑。先写审稿思路，再按固定清单逐项判定，输出可解析的 JSON 对象。"},
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
    parsed = _parse_checklist(raw)
    tokens = int(result["usage"].get("total_tokens") or estimate_tokens(body))
    if parsed is None:
        # 模型偶尔会带前导说明、包成别的东西或直接写坏 JSON。修一次比让作者重试省事。
        repair = chat(
            [
                {"role": "system", "content": "你是格式修复器，只输出可解析的 JSON 对象。"},
                {"role": "user", "content": (
                    "把下面的审稿结果整理成 JSON 对象：\n"
                    '{"checks":[{"id":"清单 id","pass":true,"quote":"","note":"","hint":""}],'
                    '"suggestions":[{"severity":"mid","code":"motivation|repetition",'
                    '"message":"","quote":"","basis":"","hint":""}]}\n'
                    "checks 必须覆盖下面清单的每一项，id 原样保留；原文没有明确说没过的项写 pass。"
                    "suggestions 只保留原文里明确提出的可选建议，原文没提就写 []。\n"
                    f"【清单】\n{checklist_prompt}\n\n【原文】\n{raw[:8000]}"
                )},
            ],
            model=selected_model,
            temperature=0,
            max_tokens=4000,
            timeout=180,
            reasoning="none",
        )
        tokens += int(repair["usage"].get("total_tokens") or 0)
        parsed = _parse_checklist(repair["text"])
    if parsed is None:
        raise LLMError("模型没有返回逐项判定（已自动修复一次）")

    ai_findings, checklist, dropped_checks = _checklist_findings(parsed["checks"], items, body, n)
    suggestions, dropped_suggestions = _grounded_ai_suggestions(parsed["suggestions"], body, n)
    ai_findings.extend(suggestions)
    group_order = {code: i for i, (code, _) in enumerate(_AI_GROUPS)}
    ai_findings.sort(key=lambda f: (
        0 if f["severity"] == "high" else 1,
        group_order.get(f["group"], len(group_order)),
        f["message"],
    ))
    ai_high = sum(1 for f in ai_findings if f["severity"] == "high")
    ai_mid = sum(1 for f in ai_findings if f["severity"] == "mid")
    failed = sum(1 for c in checklist if c["state"] == "fail")
    standard = {
        "verdict": "fail" if ai_high else "minor" if ai_mid else "pass",
        "high": ai_high,
        "mid": ai_mid,
        "filtered": dropped_checks + dropped_suggestions,
        "items": len(items),
        "passed": sum(1 for c in checklist if c["state"] == "pass"),
        "failed": failed,
        "skipped": sum(1 for c in checklist if c["state"] == "skip"),
        "resolved": 0,
        "note": "按固定清单逐项判定：清单全部通过即为通过；清单外最多记 2 条建议，不影响结论。",
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
        # 逐项判定结果：前端直接显示「对照 N 项，哪几项没过」。
        "checklist": checklist,
        # 按固定清单给结论：清单全过就是通过，只有 mid 建议不必重写。
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
