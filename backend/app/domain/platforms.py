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


# 每个平台的「写法」而不只是「字数」：这些会进改写与复检提示词。
PLAYBOOKS: dict[str, dict[str, str]] = {
    "fanqie": {
        "reader": "免费流量读者，滑动成本极低，前三章决定去留。",
        "opening": "第一章前 300 字给冲突、异常或攸关利益的选择，不铺世界观。",
        "rhythm": "每章至少一次冲突升级或信息反转；每 800–1200 字给一个小刺激。",
        "prose": "短段落，用动作和对话推进；环境描写不超过两句，少堆形容词。",
        "hooks": "章末用问句、发现、打断或倒计时收；连续两章别用同一种钩子。",
        "avoid": "慢热、大段设定说明、章末总结抒情。",
    },
    "qidian": {
        "reader": "付费与老白读者，重体系、逻辑和长线伏笔。",
        "opening": "黄金三章：主角目标、核心能力、第一个强敌或危机要尽快清楚。",
        "rhythm": "每章必须有信息增量；升级、收获、解谜至少占一项。",
        "prose": "设定用行动和对话带出，避免说明文；战斗与收益写清楚。",
        "hooks": "长线伏笔与短期目标交替，章末留悬念。",
        "avoid": "无意义日常、重复打脸、战力突然崩坏。",
    },
    "jinjiang": {
        "reader": "女性向付费读者，重人物关系、情感逻辑与文笔。",
        "opening": "开篇立人物关系与情感张力，尽快让读者站队。",
        "rhythm": "情感推进要有层次；每章至少一次关系变化或认知变化。",
        "prose": "对话与心理描写占比高，细节要准；不要用上帝视角解释情绪。",
        "hooks": "关系悬念、误会、秘密、身份反转。",
        "avoid": "人物工具化、情感突兀、说教。",
    },
    "zongheng": {
        "reader": "男频付费读者，重爽感、升级和明确目标。",
        "opening": "开局冲突明确，主角尽快拿到第一个筹码。",
        "rhythm": "打脸、收获、升级节奏稳定；章末给新目标或新威胁。",
        "prose": "利落，动作戏清楚，少抒情。",
        "hooks": "新敌人、新地图、新资源。",
        "avoid": "开局慢热、主角长期挨打不还手。",
    },
    "generic": {
        "reader": "不限平台的通用读者，先把故事讲顺。",
        "opening": "开篇抓住读者：尽快出现目标、阻碍和代价。",
        "rhythm": "每章推进一个明确变化，章末留继续读的理由。",
        "prose": "以场景和动作承载信息，少解释。",
        "hooks": "问题、决定、意外。",
        "avoid": "无冲突的过渡章、总结式收尾。",
    },
    "zhihu": {
        "reader": "短篇读者，强代入，一口气读完。",
        "opening": "第一段抛矛盾或反常结论，前 300 字建立「必须知道答案」。",
        "rhythm": "8000–30000 字一篇；中段每 1500–2000 字一个反转，结尾回扣开头。",
        "prose": "第一人称或强视角常见，口语化，少铺垫。",
        "hooks": "悬念前置、信息差、结尾反转。",
        "avoid": "慢热、长篇世界观、无意义日常。",
    },
    "heiyan": {
        "reader": "免费短篇读者，强情绪、强冲突。",
        "opening": "开头直接进冲突，三行内见血。",
        "rhythm": "每 1000–1500 字一个刺激；结尾留反转或未解问题。",
        "prose": "直白、强画面，少解释。",
        "hooks": "身份反转、背叛、复仇、绝境。",
        "avoid": "铺垫过长、说教。",
    },
    "duanzhang": {
        "reader": "短篇投放读者，前三行定生死。",
        "opening": "三行内给冲突、反转或强情绪。",
        "rhythm": "6000–20000 字，短段落，快推进。",
        "prose": "口语、画面感、少形容词。",
        "hooks": "每段末留问题。",
        "avoid": "慢热、复杂设定。",
    },
}


def platform_brief(platform: Any) -> str:
    """给模型看的平台打法：规则 + 读者预期 + 开篇/节奏/文风/钩子/禁忌。"""
    rules = platform_rules(platform)
    book = PLAYBOOKS.get(rules["id"], PLAYBOOKS["generic"])
    lines = [
        f"平台：{rules['name']}",
        f"单章字数：{rules['wordsMin']}–{rules['wordsMax']}；对话占比不低于 {rules['dialogueMin'] * 100:.0f}%；单段不超过 {rules['maxParagraphChars']} 字",
        f"章末钩子：{'必须留' if rules['chapterEndHook'] else '可选'}",
        f"标题：{rules['titlePattern']}",
        f"读者：{book['reader']}",
        f"开篇：{book['opening']}",
        f"节奏：{book['rhythm']}",
        f"文风：{book['prose']}",
        f"钩子：{book['hooks']}",
        f"避免：{book['avoid']}",
    ]
    return "\n".join(f"- {x}" for x in lines)


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
