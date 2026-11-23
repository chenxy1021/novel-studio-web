"""文本度量 + AI 痕迹检测。全部确定性、可复现，不依赖模型判断。

移植自 novel-studio/lib/metrics.js。目的：把"这篇写得像 AI"从主观评价变成可对比的数字。
注意：正则、阈值必须与 JS 版逐字对齐——checks-test 里的用例就是靠这些数字判定的。
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# 汉字区：CJK 扩展 A + 基本区 + 兼容区（JS 版 \u3400-\u4dbf\u4e00-\u9fff 之外还含兼容区）
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_SENTENCE = re.compile(r"[^。！？!?…\n]+[。！？!?…]*")
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_DIALOGUE = re.compile(r"[“\"]([^”\"]*)[”\"]")


def count_chars(text: str) -> int:
    """中文"字数"口径：汉字数 + 西文词数。"""
    s = text or ""
    return len(_CJK.findall(s)) + len(_LATIN_WORD.findall(s))


def estimate_tokens(text: str) -> int:
    """token 估算（只用于记账与预算对比，不追求分词器级精确）。

    中文按 ~1 token/字，ASCII 按 ~4 字符/token，标点折半。
    真实用量以模型返回的 usage 为准，没有时用这个数兜底。
    """
    s = text or ""
    if not s:
        return 0
    cjk = ascii_ = punct = 0
    for ch in s:
        cp = ord(ch)
        if 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF:
            cjk += 1
        elif 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:  # 　-〿 / ＀-￯
            punct += 1
        elif cp < 128:
            ascii_ += 1
        else:
            cjk += 1
    return math.ceil(cjk + punct * 0.5 + ascii_ / 4)


def _std(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _round(x: float, ndigits: int) -> float:
    """对齐 JS 的 toFixed：取 double 的精确十进制值，再按「四舍五入、进位取绝对值更大的」。

    V8 实现：先转成精确十进制，然后 half-up（13.25 → 13.3）。
    f-string 与内置 round() 都是 half-even（13.25 → 13.2），所以不能用。
    """
    q = Decimal(1).scaleb(-ndigits)
    return float(Decimal(x).quantize(q, rounding=ROUND_HALF_UP))


def text_metrics(text: str) -> dict[str, Any]:
    clean = (text or "").replace("\r\n", "\n").strip()
    paragraphs = [s.strip() for s in _PARAGRAPH_SPLIT.split(clean) if s.strip()]
    para_lens = [count_chars(s) for s in paragraphs]
    sentences = [s.strip() for s in _SENTENCE.findall(clean) if s.strip()]
    sent_lens = [n for n in (count_chars(s) for s in sentences) if n > 0]
    dialogue_chars = sum(count_chars(m.group(1)) for m in _DIALOGUE.finditer(clean))
    total = count_chars(clean) or 1
    mean = sum(paraLens) / len(paraLens) if (paraLens := para_lens) else 0.0
    sent_mean = sum(sent_lens) / len(sent_lens) if sent_lens else 0.0
    return {
        "chars": total,
        "paragraphs": len(paragraphs),
        "sentences": len(sent_lens),
        "dialogueRatio": _round(dialogue_chars / total, 3),
        "paragraphMean": _round(mean, 1),
        "paragraphMax": max(paraLens) if paraLens else 0,
        "paragraphBurstiness": _round(_std(paraLens) / mean if mean else 0, 3),
        "sentenceMean": _round(sent_mean, 1),
        "sentenceBurstiness": _round(_std(sent_lens) / sent_mean if sent_mean else 0, 3),
        "dashPer1000": _round(len(re.findall("——", clean)) / total * 1000, 2),
        "ellipsisPer1000": _round(len(re.findall("……", clean)) / total * 1000, 2),
    }


# AI / 网文套路痕迹规则库。severity: high 必须改，mid 建议改，low 观察项
AI_TELL_RULES: list[dict[str, Any]] = [
    {"id": "not-x-but-y", "label": "不是A，而是B 对举句", "severity": "high",
     "re": r"不是[^。！？\n]{1,20}[，,]?\s*(而是|是)[^。！？\n]{1,25}"},
    {"id": "rather-say", "label": "与其说…不如说", "severity": "high",
     "re": r"与其说[^。！？\n]{1,20}[，,]\s*不如说"},
    {"id": "as-if-density", "label": "仿佛/宛如/犹如 比喻密度", "severity": "mid",
     "re": r"(仿佛|宛如|犹如|好似)"},
    {"id": "air-froze", "label": "空气凝固 / 时间静止 类陈词", "severity": "high",
     "re": r"(空气(仿佛|似乎|好像)?(都)?(凝固|安静|静止)|时间(仿佛|似乎)?(静止|凝固)|落针可闻)"},
    {"id": "pupil-micro", "label": "瞳孔微缩 / 眼神一暗 类表情包", "severity": "mid",
     "re": r"(瞳孔(微|猛)?缩|眼神(一)?(暗|沉|冷)|嘴角(微微)?(勾|扬)起)"},
    {"id": "eyebrow-frown", "label": "皱眉 类表情包", "severity": "mid",
     "re": r"(皱着眉头|皱了皱眉|皱眉)"},
    {"id": "heart-thrill", "label": "心中一凛 / 心神一震 类内心套话", "severity": "mid",
     "re": r"(心中(一)?(凛|震|惊|沉)|心神(一)?(震|荡)|不由得|忍不住|下意识(地)?)"},
    {"id": "summary-close", "label": "章末总结句（这一刻他终于明白…）", "severity": "high",
     "re": r"(这一刻|那一瞬间|从今往后|他知道|她明白)[^。！？\n]{0,40}[。！？]\s*$", "multiline": True},
    {"id": "triad", "label": "三连排比 / 三词并列", "severity": "low",
     "re": r"[^，。！？\n]{2,6}、[^，。！？\n]{2,6}、[^，。！？\n]{2,6}"},
    {"id": "empty-adj", "label": "空洞形容词堆叠（无尽的/深深的/淡淡的）", "severity": "mid",
     "re": r"(无尽|深深|淡淡|缓缓|静静|默默|微微)(的|地)"},
    {"id": "eye-cliche", "label": "眼眸 / 目光深邃 类眼神陈词", "severity": "mid",
     "re": r"(眼眸|目光(深邃|幽深|复杂))"},
    {"id": "inner-cliche", "label": "心中一动 / 内心复杂 / 心情久久不能平静", "severity": "mid",
     "re": r"(心中一动|内心复杂|心情久久不能平静)"},
    {"id": "explain-emotion", "label": "直接解释情绪（他感到愤怒）", "severity": "mid",
     "re": r"(感到|感觉到|心里(很|有些|无比))(愤怒|悲伤|害怕|紧张|难过|开心|痛苦|兴奋)"},
]


def detect_ai_tells(text: str, limit: int = 40) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    for rule in AI_TELL_RULES:
        flags = re.MULTILINE if rule.get("multiline") else 0
        rex = re.compile(rule["re"], flags)
        total = 0
        samples: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            for m in rex.finditer(line):
                total += 1
                if len(samples) < 3:
                    samples.append({"line": i + 1, "text": m.group(0)[:40]})
        if total:
            hits.append({"id": rule["id"], "label": rule["label"], "severity": rule["severity"],
                         "count": total, "samples": samples, "per1000": 0.0})
    chars = count_chars(text) or 1
    for h in hits:
        h["per1000"] = _round(h["count"] / chars * 1000, 2)
    hits.sort(key=lambda h: h["per1000"], reverse=True)
    return hits[:limit]


def verdict(metrics: dict[str, Any], tells: list[dict[str, Any]]) -> dict[str, Any]:
    """一句话体检结论，供工具输出首行使用。"""
    high = sum(t["count"] for t in tells if t["severity"] == "high")
    mid = sum(t["count"] for t in tells if t["severity"] == "mid")
    density = _round((high + mid) / (metrics.get("chars") or 1) * 1000, 2)
    flat = metrics.get("paragraphBurstiness", 1) < 0.45 or metrics.get("sentenceBurstiness", 1) < 0.5
    # 阈值唯一定义在这里（域A口径）：needs_fix 只看「差」= high≥2 或密度 >2.5/千字。
    # 其余调用方（commit / 体检 / repair）直接读 level，不再各自叠一层判定。
    if density > 2.5 or high >= 2:
        level = "差"
    elif density > 2 or high >= 1:
        level = "中"
    else:
        level = "良"
    return {"level": level, "density": density, "flatRhythm": flat, "high": high, "mid": mid}


def check_chapter_end_hook(text: str) -> dict[str, Any]:
    """章尾钩子可执行判法：取最后两段（最多 200 字），满足任一即算「有钩子」。

    网文的钩子不止问句，还有发现/反转、意外动作、被打断、倒计时、
    对话收尾、短句留白。这里只做确定性提示，不拦提交。
    """
    clean = (text or "").replace("\r\n", "\n").strip()
    if not clean:
        return {"ok": False, "reason": "正文为空，无章尾"}
    paras = [s.strip() for s in re.split(r"\n+", clean) if s.strip()]
    tail = re.sub(r"\s+", "", "".join(paras[-2:]))[-200:]
    last_para = re.sub(r"\s+", "", paras[-1]) if paras else ""
    checks = [
        ("问句收尾", r"(？|\?|吗[。！]?$|呢[。！]?$|难道|岂不|怎么|为何|为什么)"),
        ("发现/反转", r"(发现|看见|看到|意识到|原来|才明白|才知道|竟然是|竟不是|不料|没想到|不对|少了一个|多出来|不见了|变了|上面写着)"),
        ("意外动作", r"(突然|猛地|骤然|忽然|猛然|冷不丁)"),
        ("被打断/有人到场", r"(没说完|话没说完|戛然而止|停在半空|顿住|僵住|门开了|传来|脚步声|身后|有人)"),
        ("倒计时/威胁", r"(来不及|只剩|再晚|期限|到期|最后一天|今晚|明早|否则)"),
        ("对话收尾", r"[”\"]$"),
    ]
    for label, pattern in checks:
        if re.search(pattern, tail):
            return {"ok": True, "reason": f"钩子：{label}"}
    # 短句独立成段收尾：网文常用的留白 / 砸钉子写法
    if len(paras) > 1 and last_para and len(last_para) <= 10:
        return {"ok": True, "reason": "钩子：短句留白"}
    return {"ok": False, "reason": "章尾两段没有问句/发现反转/意外动作/打断/倒计时/留白，读者可能不追更"}
