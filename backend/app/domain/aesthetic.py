"""审美五项复检：文字、节奏、对话、画面、情绪。

七维评审里，硬指标（字数、AI 味、格式、章末钩子、规则冲突）已经由确定性检查
和固定清单覆盖；剩下五项只能靠读，所以单独做一次轻量评审：

- 不打「总分」，五项各自 1–5 分，并指出证据句；
- 每条不超过三句评语 + 一条可执行的改法；
- 结果落 ``ledger/aesthetic.jsonl``，按章号折叠取最新；同时记下正文指纹，
  正文改过之后前端能标出「这条评语已经过期」。

这一步只给意见，不改正文、不拦存档。
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..db import now_iso
from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from ..store import (
    append_jsonl,
    project_path,
    read_chapter,
    read_index_entry,
    read_jsonl,
)
from ..store.chapter import text_hash as chapter_text_hash
from ..store.jsonl import fold_by_key

AESTHETIC_FILE = "ledger/aesthetic.jsonl"

#: 五项的顺序固定，前端按这个顺序渲染。
DIMENSIONS: list[tuple[str, str, str]] = [
    ("wording", "文字质感", "用词准不准、句子有没有多余修饰、有没有 AI 腔的排比与总结句"),
    ("rhythm", "节奏", "长短句是否服务于场景；该快的地方有没有拖，该停的地方有没有一笔带过"),
    ("dialogue", "对话", "每个人说话是否像他自己；有没有为读者解释剧情的工具人对话"),
    ("imagery", "画面感", "能不能看见具体动作与空间；有没有拿形容词代替画面"),
    ("emotion", "情绪", "情绪有没有落到行为与代价上；有没有直接写「他很痛苦」"),
]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_json(raw: Any) -> dict[str, Any] | None:
    text = strip_fence(str(raw or "")).strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _messages(title: str, text: str) -> list[dict[str, str]]:
    dims = "\n".join(f"- {key}（{label}）：{hint}" for key, label, hint in DIMENSIONS)
    system = "\n".join([
        "你是中文小说的审美编辑。你不改稿，只按五个维度给判断，并指出证据。",
        "",
        "# 评审维度",
        dims,
        "",
        "# 打分标准（1–5 分）",
        "1 = 明显有问题，读者会出戏；2 = 及格线以下，有具体可改点；",
        "3 = 合格，能读；4 = 好，有让人记住的地方；5 = 很好，可以直接当范例。",
        "默认给 3，只有证据足够才给 4 或 5；不要为了鼓励抬分。",
        "",
        "# 硬性要求",
        "1. 每个维度必须给一条 quote：从正文里逐字摘 8–30 个字，不许改写、不许编造。",
        "2. 评语 ≤ 60 字，只说这一项；不要复述剧情。",
        "3. fix 必须是可执行的下一步（「把第三段的两个比喻删掉一个」），不是「加强描写」这种空话。",
        "4. 五项之间不要重复同一条意见；同一问题放在最相关的那一项。",
        "",
        "只输出 JSON：",
        '{"dimensions":[{"key":"wording","score":3,"quote":"","comment":"","fix":""}],',
        '"summary":"整体一句话（≤50字）"}',
    ])
    user = f"章节标题：{title}\n\n正文：\n{text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _clean_dims(raw: Any) -> list[dict[str, Any]]:
    by_key = {d.get("key"): d for d in (raw or []) if isinstance(d, dict)}
    out = []
    for key, label, _ in DIMENSIONS:
        d = by_key.get(key) or {}
        try:
            score = int(d.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        out.append({
            "key": key,
            "label": label,
            "score": max(1, min(5, score)) if score else 0,
            "quote": _text(d.get("quote"))[:80],
            "comment": _text(d.get("comment"))[:160],
            "fix": _text(d.get("fix"))[:160],
        })
    return out


def load_aesthetic(root: str | os.PathLike) -> dict[int, dict[str, Any]]:
    """按章号折叠，只留每章最新一次。"""
    rows = fold_by_key(read_jsonl(project_path(root, AESTHETIC_FILE)), "chapter")
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        n = _num(row.get("chapter"))
        if n > 0:
            out[n] = row
    return out


def rating(root: str | os.PathLike, number: int) -> dict[str, Any] | None:
    """取某一章的最新审美复检；正文已改（指纹对不上）时标 stale。"""
    row = load_aesthetic(root).get(int(number))
    if not row:
        return None
    try:
        text = read_chapter(root, int(number)) or ""
    except FileNotFoundError:
        text = ""
    stale = bool(row.get("sha256") and text and row["sha256"] != chapter_text_hash(text))
    return {**row, "stale": stale}


def aesthetic_check(
    root: str | os.PathLike,
    number: int,
    *,
    text: str | None = None,
    model: str | None = None,
    on_delta=None,
) -> dict[str, Any]:
    n = int(number)
    body = (text if text is not None else read_chapter(root, n)) or ""
    if not body.strip():
        raise ValueError(f"第{n}章没有正文，无法做审美复检")
    entry = read_index_entry(root, n) or {}
    title = _text(entry.get("title")) or f"第{n}章"
    result = chat(
        _messages(title, body),
        model=model,
        temperature=0.2,
        max_tokens=4000,
        timeout=300,
        reasoning=reasoning_for("check"),
        on_delta=on_delta,
    )
    parsed = _parse_json(result.get("text"))
    if parsed is None:
        raise LLMError(f"模型没有返回可解析的审美评审 JSON：{str(result.get('text'))[:200]}")
    dims = _clean_dims(parsed.get("dimensions"))
    scored = [d["score"] for d in dims if d["score"]]
    row = {
        "chapter": n,
        "title": title,
        "sha256": chapter_text_hash(body),
        "dimensions": dims,
        "average": round(sum(scored) / len(scored), 2) if scored else 0,
        "summary": _text(parsed.get("summary"))[:120],
        "model": str(result.get("model") or model or ""),
        "at": now_iso(),
    }
    if any(d["score"] for d in dims):
        append_jsonl(project_path(root, AESTHETIC_FILE), row)
    return {**row, "stale": False}
