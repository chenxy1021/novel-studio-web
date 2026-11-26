"""正文质量的确定性补充：跨章重复、结构统计、细纲场景功能。

这些都不是「AI 像不像」的判断，而是可以直接数出来的事实：
- 同一段六字短语在最近几章里反复出现（套话、复读、模型偷懒）；
- 本章句子/段落长短、对话占比、用字多样性；
- 细纲每一拍有没有走完「谁→想要→受阻→结果」。

给体检面板提供依据，不单独阻断写作；阻断仍由 check_chapter 的硬规则负责。
"""

from __future__ import annotations

import os
import re
from typing import Any

from ..store import chapter as chapter_store
from ..store import project_path, read_jsonl
from ..store.jsonl import fold_outline
from .metrics import lexical_diversity, text_metrics

OUTLINE_FILE = "ledger/outline.jsonl"

# 只保留汉字、字母、数字；标点和空白不参与 n-gram，避免「。他」这种碎片。
_CLEAN = re.compile(r"[^㐀-䶿一-鿿A-Za-z0-9]+")
_STOP_CHARS = set("的了是在和与就都也不没很我你他她它们这那有对说")
_ARROW = re.compile(r"\s*(?:→|->|➜|=>|—>)\s*")


def _clean(text: str) -> str:
    return _CLEAN.sub("", text or "")


def _ngrams(text: str, size: int) -> list[str]:
    clean = _clean(text)
    return [clean[i:i + size] for i in range(0, max(0, len(clean) - size + 1))]


def _informative(gram: str) -> bool:
    """全由「的了是在」这类字组成的六字格没有信息量，不作为重复项报出。"""
    return len(set(gram) - _STOP_CHARS) >= 3


def cross_chapter_repeats(
    root: str | os.PathLike,
    number: int,
    *,
    lookback: int = 8,
    size: int = 6,
    min_chapters: int = 2,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """本章里反复出现在最近几章的短语。

    ``chapters`` 是这些短语出现过的更早章号；``count`` 是本章出现次数。
    只看最近 ``lookback`` 章：再久以前的重复多半是设定词或人物名，不算套话。
    """
    n = int(number)
    current = chapter_store.read_chapter(root, n) or ""
    if not current.strip():
        return []
    grams = _ngrams(current, size)
    if not grams:
        return []

    prior: dict[str, set[int]] = {}
    for ch in range(max(1, n - lookback), n):
        body = chapter_store.read_chapter(root, ch) or ""
        if not body.strip():
            continue
        for gram in set(_ngrams(body, size)):
            prior.setdefault(gram, set()).add(ch)

    counts: dict[str, int] = {}
    for gram in grams:
        counts[gram] = counts.get(gram, 0) + 1

    rows: list[dict[str, Any]] = []
    for gram, count in counts.items():
        chapters = sorted(prior.get(gram) or ())
        if len(chapters) < min_chapters and count < 3:
            continue
        if not _informative(gram):
            continue
        rows.append({
            "phrase": gram,
            "count": count,
            "chapters": chapters,
            "severity": "mid" if len(chapters) >= min_chapters else "low",
        })
    rows.sort(key=lambda r: (-len(r["chapters"]), -r["count"], r["phrase"]))
    return rows[:limit]


def repeated_sentences(text: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """同一章里原样重复的句子（8 字以上）；短对白不算，那是人物口头禅。"""
    seen: dict[str, int] = {}
    for raw in re.split(r"[。！？!?…\n]+", text or ""):
        s = raw.strip()
        if len(_clean(s)) < 8:
            continue
        seen[s] = seen.get(s, 0) + 1
    rows = [{"sentence": s, "count": c} for s, c in seen.items() if c > 1]
    rows.sort(key=lambda r: (-r["count"], -len(r["sentence"])))
    return rows[:limit]


def structure(text: str) -> dict[str, Any]:
    """结构统计：长短句/段落、对话、标点、用字多样性。"""
    m = text_metrics(text)
    paragraphs = [p for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    long_paragraphs = sum(1 for p in paragraphs if len(_clean(p)) > 300)
    short_sentences = sum(
        1 for s in re.split(r"[。！？!?…\n]+", text or "") if 0 < len(_clean(s)) < 8
    )
    return {
        **m,
        "lexicalDiversity": lexical_diversity(text),
        "longParagraphs": long_paragraphs,
        "longParagraphShare": round(long_paragraphs / len(paragraphs), 3) if paragraphs else 0,
        "shortSentences": short_sentences,
        "shortSentenceShare": round(short_sentences / m["sentences"], 3) if m["sentences"] else 0,
    }


def scene_beats(outline_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    """细纲每一拍的「谁→想要→受阻→结果」走完了没有。

    不判断内容好坏，只数箭头：少一段就是这一拍没交代清楚，写正文时最容易漏。
    """
    rows: list[dict[str, Any]] = []
    for beat in (outline_row or {}).get("beats") or []:
        text = str(beat or "").strip()
        if not text:
            continue
        parts = [p for p in _ARROW.split(text) if p.strip()]
        rows.append({
            "beat": text,
            "parts": len(parts),
            "ok": len(parts) >= 3,
            "who": parts[0] if parts else "",
            "result": parts[-1] if parts else "",
        })
    return rows


def _outline_row(root: str | os.PathLike, number: int) -> dict[str, Any] | None:
    for row in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))):
        if int(row.get("chapter") or 0) == int(number):
            return row
    return None


def quality_report(root: str | os.PathLike, number: int) -> dict[str, Any]:
    """体检回包里的 ``quality``。任何一步失败都不影响正文体检。"""
    n = int(number)
    try:
        body = chapter_store.read_chapter(root, n) or ""
    except (FileNotFoundError, ValueError):
        body = ""
    if not body.strip():
        return {"repeats": [], "sentences": [], "structure": {}, "scenes": [], "beatsMissing": []}
    scenes = scene_beats(_outline_row(root, n))
    return {
        "repeats": cross_chapter_repeats(root, n),
        "sentences": repeated_sentences(body),
        "structure": structure(body),
        "scenes": scenes,
        "beatsMissing": [s["beat"] for s in scenes if not s["ok"]],
    }
