"""平台规则集：篇幅区间、开头钩子、章末钩子、单段字数上限、对话比下限、标题格式。

移植自 novel-studio/lib/platforms.js。作为确定性校验依据，面板与 chapter_commit 共用。
"""

from __future__ import annotations

import re
from typing import Any

PLATFORMS: dict[str, dict[str, Any]] = {
    "fanqie": {
        "id": "fanqie", "name": "番茄小说",
        "wordsMin": 2000, "wordsMax": 3500,
        "openingHook": "前 3 章每章至少一次冲突升级，章末留钩子",
        "chapterEndHook": True, "maxParagraphChars": 120, "dialogueMin": 0.15,
        "titlePattern": "第N章 标题",
    },
    "qidian": {
        "id": "qidian", "name": "起点中文网",
        "wordsMin": 2500, "wordsMax": 4000,
        "openingHook": "黄金三章，开局给钩子", "chapterEndHook": True,
        "maxParagraphChars": 150, "dialogueMin": 0.1,
        "titlePattern": "第N章 标题",
    },
    "jinjiang": {
        "id": "jinjiang", "name": "晋江文学城",
        "wordsMin": 3000, "wordsMax": 5000,
        "openingHook": "开篇立人物关系", "chapterEndHook": True,
        "maxParagraphChars": 150, "dialogueMin": 0.3,
        "titlePattern": "不用「第N章」式标题，直接写标题名",
    },
    "zongheng": {
        "id": "zongheng", "name": "纵横中文网",
        "wordsMin": 2500, "wordsMax": 4000,
        "openingHook": "开局冲突明确", "chapterEndHook": True,
        "maxParagraphChars": 150, "dialogueMin": 0.1,
        "titlePattern": "第N章 标题",
    },
    "generic": {
        "id": "generic", "name": "通用",
        "wordsMin": 1500, "wordsMax": 5000,
        "openingHook": "开篇抓住读者", "chapterEndHook": False,
        "maxParagraphChars": 200, "dialogueMin": 0.0,
        "titlePattern": "第N章 标题",
    },
    # 短篇平台：走 story-short-* 那一套方法
    "zhihu": {
        "id": "zhihu", "name": "知乎盐言", "short": True,
        "wordsMin": 8000, "wordsMax": 30000,
        "openingHook": "第一段就要抛出矛盾或反转", "chapterEndHook": True,
        "maxParagraphChars": 120, "dialogueMin": 0.2,
        "titlePattern": "直接写标题，不用「第N章」",
    },
    "heiyan": {
        "id": "heiyan", "name": "黑岩", "short": True,
        "wordsMin": 5000, "wordsMax": 20000,
        "openingHook": "开头直接进冲突", "chapterEndHook": True,
        "maxParagraphChars": 120, "dialogueMin": 0.15,
        "titlePattern": "直接写标题",
    },
    "duanzhang": {
        "id": "duanzhang", "name": "点众短篇", "short": True,
        "wordsMin": 6000, "wordsMax": 20000,
        "openingHook": "开头三行内给冲突", "chapterEndHook": True,
        "maxParagraphChars": 120, "dialogueMin": 0.15,
        "titlePattern": "直接写标题",
    },
}

_ALIAS = {
    "番茄": "fanqie", "番茄小说": "fanqie",
    "起点": "qidian", "起点中文网": "qidian",
    "晋江": "jinjiang", "晋江文学城": "jinjiang",
    "纵横": "zongheng", "纵横中文网": "zongheng",
    "通用": "generic", "未定": "generic",
    "知乎": "zhihu", "知乎盐言": "zhihu", "盐言故事": "zhihu", "盐选": "zhihu",
    "黑岩": "heiyan", "黑岩小说": "heiyan",
    "点众": "duanzhang", "点众短篇": "duanzhang",
}

_NTH_CHAPTER_TITLE = re.compile(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章")


def platform_rules(platform: Any) -> dict[str, Any]:
    """把平台名/ID 归一成规则对象。认不出就回通用规则，绝不让校验因平台名崩掉。"""
    if not platform:
        return PLATFORMS["generic"]
    key = str(platform).strip()
    if key in PLATFORMS:
        return PLATFORMS[key]
    if key in _ALIAS:
        return PLATFORMS[_ALIAS[key]]
    return next((p for p in PLATFORMS.values() if p["name"] == key), PLATFORMS["generic"])


def check_platform_format(text: Any, title: Any, metrics: dict[str, Any] | None,
                          rules: dict[str, Any] | None = None, opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """按平台规则校验一章正文，返回 {pass, issues:[{code,severity,message}]}。"""
    rules = rules or PLATFORMS["generic"]
    opts = opts or {}
    issues: list[dict[str, str]] = []
    chars = (metrics or {}).get("chars") or 0
    hard_min = int(opts.get("minChars") or 0)
    if hard_min and chars < hard_min:
        # 硬下限：长篇每章 1800 字起（项目侧统一传入；超短篇项目传 0）
        issues.append({"code": "words-below", "severity": "hard", "message": f"{chars} 字，低于每章硬下限 {hard_min} 字"})
    elif chars < rules["wordsMin"]:
        issues.append({"code": "words-below", "severity": "info",
                       "message": f"{chars} 字，低于{rules['name']}要求 {rules['wordsMin']} 字"})
    elif chars > rules["wordsMax"]:
        issues.append({"code": "words-above", "severity": "info",
                       "message": f"{chars} 字，超过{rules['name']}上限 {rules['wordsMax']} 字"})
    dr = (metrics or {}).get("dialogueRatio") or 0
    if dr < rules["dialogueMin"]:
        issues.append({"code": "dialogue-low", "severity": "info",
                       "message": f"对话比 {dr * 100:.0f}%，低于{rules['name']}建议 {rules['dialogueMin'] * 100:.0f}%"})
    max_para = (metrics or {}).get("paragraphMax") or 0
    if max_para > rules["maxParagraphChars"]:
        issues.append({"code": "paragraph-too-long", "severity": "info",
                       "message": f"最长段落 {max_para} 字，超过单段上限 {rules['maxParagraphChars']} 字"})
    if rules["id"] == "jinjiang" and _NTH_CHAPTER_TITLE.match(str(title or "")):
        issues.append({"code": "title-pattern", "severity": "info", "message": f"晋江不建议「第N章」式标题：{title}"})
    return {"pass": not any(i["severity"] in ("mid", "hard") for i in issues), "issues": issues}
