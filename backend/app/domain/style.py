"""文风 v2：读写、合并、校验、优先级解析与提示词渲染。

存储位置沿用 ``bible.json`` 的 ``style`` 对象。旧字段 ``pov/tense/samples/banned/notes``
原样兼容；缺字段一律按空处理，不阻塞加载。本模块只做纯函数，读写由路由层负责。

优先级（见 design/ux §9.1）：**当前请求（本批 override） > 本书 style > 平台默认**。
事实与表达分开：文风只决定「怎么写」，不得改变细纲事件、人物关系与已发生事实。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import StyleInvalid
from .platforms import platform_rules
from .style_presets import get_preset

VERSION = 2

# 规范字段（顺序即界面顺序）。``dialogue`` 是设计稿里的旧键，读取时映射到 ``dialogueRatio``。
SCALAR_FIELDS = ("pov", "person", "sentence", "paragraph", "rhythm", "dialogueRatio")
LIST_FIELDS = ("banned", "samples", "references")
TEXT_FIELDS = ("notes", "tense", "presetId")
CANONICAL_FIELDS = (*SCALAR_FIELDS, *LIST_FIELDS, *TEXT_FIELDS)

LABELS = {
    "pov": "视角",
    "person": "叙述人称",
    "sentence": "句长",
    "paragraph": "段落长度",
    "rhythm": "节奏",
    "dialogueRatio": "对话比例",
    "banned": "禁用表达",
    "samples": "样章",
    "references": "参考作者/作品",
    "notes": "补充说明",
    "presetId": "文风预设",
}

# design §6.4 的注入位置：细纲只吃结构相关维度，正文吃全部。
STAGE_FIELDS = {
    "outline": ("pov", "person", "rhythm", "banned", "notes"),
    "prose": (
        "pov", "person", "sentence", "paragraph", "rhythm", "dialogueRatio",
        "banned", "samples", "references", "notes",
    ),
}

LIMITS = {
    "banned": 30,
    "banned_item": 40,
    "samples": 3,
    "sample_text": 800,
    "sample_label": 12,
    "references": 5,
    "reference_item": 40,
    "notes": 500,
}

# 平台默认禁用表达：只是起点，作者可以在书里覆盖。
DEFAULT_BANNED = ["他很难过", "空气仿佛凝固"]

_SENTENCE_SHORT = {"fanqie", "heiyan", "duanzhang"}
_RHYTHM_TIGHT = {"fanqie", "heiyan", "duanzhang", "zhihu"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _normalize_banned(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([_text(x) for x in value if _text(x)])


def _normalize_samples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append({"text": text})
            continue
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text"))
        if not text:
            continue
        row: dict[str, Any] = {**item, "text": text}
        if "label" in item:
            row["label"] = _text(item.get("label"))
        if "note" in item:
            row["note"] = _text(item.get("note"))
        out.append(row)
    return out


def _normalize_references(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
            continue
        if not isinstance(item, dict):
            continue
        row = dict(item)
        for key in ("author", "work", "note"):
            if key in row:
                row[key] = _text(row.get(key))
        if any(_text(row.get(k)) for k in ("author", "work", "note")):
            out.append(row)
    return out


def normalize_style(raw: Any) -> dict[str, Any]:
    """Return a loadable style doc. Unknown fields are preserved (never silently dropped)."""
    src: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    out = dict(src)
    out["version"] = VERSION
    for field in SCALAR_FIELDS:
        if field == "dialogueRatio" and "dialogueRatio" not in src and src.get("dialogue") not in (None, ""):
            out[field] = _text(src.get("dialogue"))
        else:
            out[field] = _text(src.get(field))
    for field in TEXT_FIELDS:
        out[field] = _text(src.get(field))
    out["banned"] = _normalize_banned(src.get("banned"))
    out["samples"] = _normalize_samples(src.get("samples"))
    out["references"] = _normalize_references(src.get("references"))
    return out


def normalize_patch(raw: Any) -> dict[str, Any]:
    """Only the fields actually submitted, normalized. Used for per-batch overrides."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if "dialogue" in raw and "dialogueRatio" not in raw:
        out["dialogueRatio"] = _text(raw.get("dialogue"))
    for field in SCALAR_FIELDS:
        if field in raw:
            out[field] = _text(raw.get(field))
    for field in TEXT_FIELDS:
        if field in raw:
            out[field] = _text(raw.get(field))
    if "banned" in raw:
        out["banned"] = _normalize_banned(raw.get("banned"))
    if "samples" in raw:
        out["samples"] = _normalize_samples(raw.get("samples"))
    if "references" in raw:
        out["references"] = _normalize_references(raw.get("references"))
    return out


def validate_patch(patch: Any) -> None:
    """Length / shape checks; raises ``StyleInvalid`` (HTTP 400) with a field name."""
    if not isinstance(patch, dict):
        raise StyleInvalid("文风必须是对象", field="style")

    banned = patch.get("banned")
    if banned is not None:
        if not isinstance(banned, list) or not all(isinstance(x, str) for x in banned):
            raise StyleInvalid("禁用表达必须是字符串数组", field="banned")
        if len(banned) > LIMITS["banned"]:
            raise StyleInvalid(f"禁用表达最多 {LIMITS['banned']} 条", field="banned")
        for item in banned:
            if len(item) > LIMITS["banned_item"]:
                raise StyleInvalid(f"每条禁用表达最多 {LIMITS['banned_item']} 字", field="banned")

    samples = patch.get("samples")
    if samples is not None:
        if not isinstance(samples, list):
            raise StyleInvalid("样章必须是数组", field="samples")
        if len(samples) > LIMITS["samples"]:
            raise StyleInvalid(f"样章最多 {LIMITS['samples']} 段", field="samples")
        for item in samples:
            if isinstance(item, str):
                if len(item) > LIMITS["sample_text"]:
                    raise StyleInvalid(f"每段样章最多 {LIMITS['sample_text']} 字", field="samples")
                continue
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise StyleInvalid("样章元素必须是字符串或 {text, note?} 对象", field="samples")
            if len(item["text"]) > LIMITS["sample_text"]:
                raise StyleInvalid(f"每段样章最多 {LIMITS['sample_text']} 字", field="samples")
            if "note" in item and not isinstance(item.get("note"), str):
                raise StyleInvalid("样章 note 必须是字符串", field="samples")
            if len(_text(item.get("label"))) > LIMITS["sample_label"]:
                raise StyleInvalid(f"样章标签最多 {LIMITS['sample_label']} 字", field="samples")

    references = patch.get("references")
    if references is not None:
        if not isinstance(references, list) or not all(isinstance(x, str) for x in references):
            raise StyleInvalid("参考作者/作品必须是字符串数组", field="references")
        if len(references) > LIMITS["references"]:
            raise StyleInvalid(f"参考作者/作品最多 {LIMITS['references']} 条", field="references")
        for item in references:
            if len(item) > LIMITS["reference_item"]:
                raise StyleInvalid(f"每条参考最多 {LIMITS['reference_item']} 字", field="references")

    notes = patch.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise StyleInvalid("补充说明必须是字符串", field="notes")
    if isinstance(notes, str) and len(notes) > LIMITS["notes"]:
        raise StyleInvalid(f"补充说明最多 {LIMITS['notes']} 字", field="notes")

    for field in ("pov", "person", "sentence", "paragraph", "rhythm", "dialogueRatio", "tense", "presetId"):
        if field in patch and patch[field] is not None and not isinstance(patch[field], str):
            raise StyleInvalid(f"{LABELS.get(field, field)} 必须是字符串", field=field)

    preset_id = patch.get("presetId")
    if preset_id not in (None, "") and get_preset(preset_id) is None:
        raise StyleInvalid(f"未知的文风预设：{preset_id}", field="presetId")


def merge_style(current: Any, patch: Any) -> dict[str, Any]:
    """Partial merge: only submitted keys change; everything else is preserved."""
    stored: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    clean = normalize_patch(patch)
    stored.update(clean)
    stored["version"] = VERSION
    stored["updatedAt"] = _now()
    return normalize_style(stored)


def has_values(style: Any) -> bool:
    """True when the author actually set anything (ignores version/updatedAt/tense)."""
    doc = normalize_style(style)
    if any(doc.get(f) for f in SCALAR_FIELDS):
        return True
    if doc.get("tense") or doc.get("notes") or doc.get("presetId"):
        return True
    return bool(doc.get("banned") or doc.get("samples") or doc.get("references"))


def platform_default_style(platform: Any) -> dict[str, Any]:
    """Defaults used only for dimensions the book leaves empty."""
    rules = platform_rules(platform)
    pid = str(rules.get("id") or "generic")
    max_para = int(rules.get("maxParagraphChars") or 200)
    dialogue_min = float(rules.get("dialogueMin") or 0)
    if max_para <= 120:
        paragraph = "1–3 句"
    elif max_para <= 150:
        paragraph = "3–5 句"
    else:
        paragraph = "长段"
    if dialogue_min < 0.15:
        dialogue = "低 10–20%"
    elif dialogue_min < 0.3:
        dialogue = "中 20–40%"
    else:
        dialogue = "高 40%+"
    return normalize_style({
        "version": VERSION,
        "pov": "第三人称限制",
        "person": "他/她",
        "sentence": "短句为主" if pid in _SENTENCE_SHORT else "长短交错",
        "paragraph": paragraph,
        "rhythm": "紧" if pid in _RHYTHM_TIGHT else "张弛",
        "dialogueRatio": dialogue,
        "banned": list(DEFAULT_BANNED),
        "samples": [],
        "references": [],
        "notes": "",
        "tense": "",
    })


def resolve_style(
    bible_style: Any,
    platform: Any,
    override: Any = None,
) -> tuple[dict[str, Any], str]:
    """Merge platform defaults → book style → per-batch override.

    Returns ``(effective, source)`` where source is ``platform`` / ``book`` / ``book+override``.
    Explicit empty values in the override clear that dimension for this batch.
    """
    defaults = platform_default_style(platform)
    book = normalize_style(bible_style)
    patch = normalize_patch(override)
    effective = dict(defaults)
    for field in CANONICAL_FIELDS:
        if book.get(field) not in (None, "", [], {}):
            effective[field] = book[field]
    for field in CANONICAL_FIELDS:
        if field in patch:  # presence, not truthiness: empty list clears
            effective[field] = patch[field]
    has_book = has_values(book)
    has_override = bool(patch)
    if has_override:
        source = "book+override"
    elif has_book:
        source = "book"
    else:
        source = "platform"
    return normalize_style(effective), source


def style_applied(bible_style: Any, platform: Any, override: Any = None) -> dict[str, Any]:
    effective, source = resolve_style(bible_style, platform, override)
    return {"source": source, "effective": effective}


def _format_reference(item: Any) -> str:
    if isinstance(item, dict):
        author = _text(item.get("author"))
        work = _text(item.get("work"))
        note = _text(item.get("note"))
        head = "《".join([author, work]).strip("《") if author or work else ""
        head = f"{author}《{work}》" if author and work else (work or author)
        return f"{head}：{note}" if note else head
    return _text(item)


def render_style(style: Any, *, stage: str = "prose", max_samples: int = 2) -> str:
    """Render the effective style as prompt text; never includes sample prose copying."""
    doc = normalize_style(style)
    fields = STAGE_FIELDS.get(stage, STAGE_FIELDS["prose"])
    lines: list[str] = []
    for field in fields:
        value = doc.get(field)
        if field == "banned":
            if value:
                lines.append(f"- {LABELS[field]}：{'、'.join(str(x) for x in value[:20])}")
        elif field == "samples":
            samples = value if isinstance(value, list) else []
            for sample in samples[:max_samples]:
                text = str(sample.get("text") if isinstance(sample, dict) else sample).strip()
                if not text:
                    continue
                label = _text(sample.get("label")) if isinstance(sample, dict) else ""
                head = f"{LABELS[field]}（{label}）" if label else LABELS[field]
                lines.append(f"- {head}：{text}")
        elif field == "references":
            refs = [_format_reference(x) for x in (value if isinstance(value, list) else [])]
            refs = [x for x in refs if x]
            if refs:
                lines.append(f"- {LABELS[field]}（只学风格特征，不复制原文）：{'；'.join(refs[:5])}")
        elif value:
            lines.append(f"- {LABELS[field]}：{value}")
    parts: list[str] = []
    preset = get_preset(doc.get("presetId"))
    if preset:
        parts.append(
            f"【文风参照·{preset.get('name') or preset.get('id')}】"
            "只参考写法，不复制原句；本书字段优先。"
        )
        for trait in (preset.get("traits") or [])[:6]:
            text = str(trait).strip()
            if text:
                parts.append(f"- 参照：{text}")
    if lines:
        if parts:
            parts.append("")
        parts.append("文风只决定「怎么写」；细纲事件、人物关系与已发生事实不得因文风改变。")
        parts.extend(lines)
    if not parts:
        return "（未指定；按平台默认）"
    return "\n".join(parts)


def style_block(style: Any, override: Any = None, *, stage: str = "prose") -> str:
    """Prompt block for a book style with an optional per-batch override.

    Priority: ``override > book style``. Empty override values clear the dimension.
    """
    book = normalize_style(style)
    patch = normalize_patch(override)
    merged = dict(book)
    merged.update(patch)
    return render_style(merged, stage=stage)
