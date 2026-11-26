"""写作：点「写第 N 章」时，先出本章细纲，再照细纲写正文。

旧插件把这两步拆给策划（outlines-gen）和写作会话（novel_context → 写 → commit）；
网页版需要一个按钮就能推进，所以在同一个请求里顺序完成：

1. 细纲：本卷大纲切片 + 段落纲台阶 + 设定 + 伏笔 + 上一章结尾 → 3–6 个可观察节拍；
   机器块 <<<OUTLINE_JSON>>> 落 ledger/outline.jsonl，Markdown 正文留给作者看。
2. 正文：细纲 + 人物卡 + 规则 + 文风 + 平台打法（+ 虐文公式）→ 本章正文；
   落 chapters/NNN-标题.md 与 chapters/index.json，状态为「待确认」，不进存档。

模型调用都在锁外；落盘时再拿锁，失败时正文一个字都不写。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
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
    save_project,
    write_chapter as write_chapter_file,
    written_through,
)
from ..store.jsonl import fold_foreshadow, fold_outline
from . import prompts, style as style_mod
from .errors import (
    ChapterExists,
    ChapterOutOfRange,
    NoForeshadowError,
    NoOutlineError,
    NoOutlineRow,
    ProseTooShort,
)
from .continuity import character_line, rule_line
from .memory import clamp_summary, characters_mentioned, load_volumes
from .metrics import count_chars, estimate_tokens
from .platforms import platform_rules
from .references import build_reference_pack, stage_for, volume_slice
from .review import _entry_from_text
from .skills import SKILL_KEYS, read_skills

OUTLINE_FILE = "ledger/outline.jsonl"
SEGMENTS_FILE = "ledger/segments.jsonl"
FORESHADOW_FILE = "ledger/foreshadow.jsonl"
REVIEW_FILE = "ledger/review.jsonl"
USAGE_FILE = "metrics/usage.jsonl"


def _apply_skill_override(project: dict[str, Any], override: Any) -> dict[str, Any]:
    """Per-batch switches: book defaults, then this batch's explicit choices."""
    if not isinstance(override, dict) or not override:
        return project
    merged = read_skills(project)
    for key in SKILL_KEYS:
        if isinstance(override.get(key), bool):
            merged[key] = override[key]
    if not project.get("nuewen"):
        merged["nuewen"] = False
    return {**project, "writingSkills": merged}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    return project


def _prose_candidate_score(text: str, target: int) -> float:
    """多稿候选的确定性挑法：先够长，再少套路，最后看节奏。

    这是「挑一稿」不是「打分」，不调模型；作者仍可以整章重写或段落改写。
    """
    from .metrics import detect_ai_tells, text_metrics

    m = text_metrics(text)
    tells = detect_ai_tells(text)
    high = sum(1 for t in tells if t.get("severity") == "high")
    mid = sum(1 for t in tells if t.get("severity") == "mid")
    length = min(m["chars"] / target, 1.0) if target else 0.0
    return (
        length * 3
        - high * 1.5
        - mid * 0.3
        + m["sentenceBurstiness"] * 0.5
        + min(m["dialogueRatio"], 0.5)
    )


def _outline_row(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    for row in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))):
        if int(row.get("chapter") or 0) == chapter:
            return row
    return None


def _stage_for(root: str | os.PathLike, chapter: int) -> dict[str, Any] | None:
    """兼容旧名：段落纲台阶查询已移到 ``references``。"""
    return stage_for(root, chapter)


def _volume_slice(outline: str, volumes: list[dict[str, Any]], chapter: int) -> tuple[str, dict[str, Any] | None]:
    """兼容旧名：本卷大纲切片已移到 ``references``。"""
    return volume_slice(outline, volumes, chapter)


def _nuewen_block(text: str) -> str:
    return f"""【虐文原则（必须执行）】
{text}
- 每个反转必须有因果链：性格 → 压力下的选择 → 代价落地；禁止天灾、巧合、误会降智。
- 反转要咬合：一个人的结局要成为另一个人的压力源。
- 先甜后虐：甜要短、具体、真；虐要安静，用动作、停顿、重复细节承载，不写嚎哭式抒情和总结句。
- 这一章只推进一条反转，不要十条线一起发刀；章末把代价落地。
"""


def _focus_block(focus: Any) -> str:
    """【本章额外强调】最多 5 条，按传入顺序放在提示词最前面。"""
    if not isinstance(focus, list):
        return ""
    lines: list[str] = []
    for item in focus[:5]:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("key") or "").strip()
            if not label:
                continue
            kind = str(item.get("type") or "").strip()
            key = str(item.get("key") or "").strip()
            suffix = f"（{kind}:{key}）" if kind and key else ""
            lines.append(f"- {label}{suffix}")
        elif item:
            lines.append(f"- {str(item).strip()}")
    if not lines:
        return ""
    return "【本章额外强调（最多 5 条，按顺序优先落实）】\n" + "\n".join(lines) + "\n\n"


def _style_text(
    bible: dict[str, Any],
    project: dict[str, Any],
    style_override: Any,
    *,
    stage: str,
    samples: bool = True,
) -> str:
    """本批生效文风：平台默认 → 本书 → 本批 override，渲染成提示词块。

    ``samples=False``（写作技能「文风样本」关闭）时不注入样章语感。
    """
    base, _ = style_mod.resolve_style(bible.get("style"), project.get("platform"), None)
    if not samples:
        base = {**base, "samples": []}
    return style_mod.style_block(base, style_override, stage=stage)


def _section_text(pack: dict[str, Any], key: str) -> str:
    for section in pack.get("sections") or []:
        if section.get("key") == key:
            return str(section.get("text") or "")
    return ""


def _skill_modules(root: str | os.PathLike, skills: dict[str, bool], names: tuple[str, ...],
                   *, cap: int = 1600) -> str:
    """按写作技能开关加载 ``prompts/`` 模块；每个模块最多注入 ``cap`` 字，超出截断并标注。"""
    parts: list[str] = []
    for name in names:
        if not skills.get(name, True):
            continue
        try:
            text = prompts.load(name, root=root).strip()
        except prompts.PromptNotFound:
            continue
        if not text:
            continue
        original = len(text)
        if original > cap:
            text = text[:cap] + f"\n…（已截断到 {cap} 字，原 {original} 字）"
        parts.append(f"## {name}\n{text}")
    return "\n\n".join(parts)


def _settings_brief(bible: dict[str, Any], *, chapter: int) -> dict[str, str]:
    chars = [line for line in (character_line(c) for c in (bible.get("characters") or [])[:12]) if line]
    rules = [line for line in (rule_line(r) for r in (bible.get("rules") or [])[:10]) if line]

    world = []
    for w in (bible.get("world") or [])[:6]:
        name = str(w.get("name") or "").strip()
        if name:
            world.append(f"【世界·{name}】{w.get('text') or ''}")

    style = bible.get("style") if isinstance(bible.get("style"), dict) else {}
    style_lines = []
    if style.get("notes"):
        style_lines.append(f"文风要求：{style.get('notes')}")
    if style.get("pov"):
        style_lines.append(f"视角：{style.get('pov')}")
    if style.get("banned"):
        style_lines.append("禁用表达：" + "、".join(str(x) for x in style.get("banned")[:20]))
    samples = style.get("samples") if isinstance(style.get("samples"), list) else []
    if samples:
        first = samples[0]
        style_lines.append("文风样本：" + str(first.get("text") if isinstance(first, dict) else first)[:300])

    return {
        "chars": "\n".join(chars) or "（未登记人物卡）",
        "rules": "\n".join(rules) or "（无）",
        "world": "\n".join(world) or "（无）",
        "style": "\n".join(style_lines) or "（未指定）",
    }


def _foreshadow_brief(root: str | os.PathLike, chapter: int) -> tuple[str, str]:
    rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
    open_rows = [r for r in rows if r.get("status") == "open"]
    due = [r for r in open_rows if int(r.get("dueChapter") or 0) == chapter]
    plant = [r for r in open_rows if int(r.get("plantedChapter") or 0) == chapter]
    rest = [r for r in open_rows if r not in due and r not in plant]

    def fmt(f: dict[str, Any], tag: str = "") -> str:
        bits = [f"{f.get('name')}｜第{f.get('plantedChapter')}章埋·计划第{f.get('dueChapter') or '?'}章收"]
        if f.get("plantBeat"):
            bits.append(f"埋点:{f.get('plantBeat')}")
        if f.get("revealChange"):
            bits.append(f"揭开后:{f.get('revealChange')}")
        if f.get("hint"):
            bits.append(f"中途提示:{f.get('hint')}")
        return (f"【{tag}】" if tag else "") + "；".join(bits)

    this = [fmt(f, "本章应收") for f in due] + [fmt(f, "本章应埋") for f in plant]
    return "\n".join(this), "\n".join(fmt(f) for f in rest[:40])


def _foreshadow_schedule(root: str | os.PathLike, frm: int, to: int) -> str:
    """一批的伏笔日程：按章列出应埋/应收，批次细纲据此分配节拍。"""
    rows = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
    open_rows = [r for r in rows if r.get("status") == "open"]
    lines: list[str] = []
    for n in range(frm, to + 1):
        due = [r for r in open_rows if int(r.get("dueChapter") or 0) == n]
        plant = [r for r in open_rows if int(r.get("plantedChapter") or 0) == n]
        if not due and not plant:
            continue
        bits: list[str] = []
        for f in due:
            bits.append(f"收「{f.get('name')}」（第{f.get('plantedChapter')}章埋）")
        for f in plant:
            bits.append(f"埋「{f.get('name')}」（计划第{f.get('dueChapter') or '?'}章收）")
        lines.append(f"- 第{n}章：{'；'.join(bits)}")
    return "\n".join(lines) or "（本批没有到期/应埋的伏笔；可从下面挑一条续，也可不埋）"


def _recent_outlines(root: str | os.PathLike, chapter: int, limit: int = 6) -> str:
    rows = [r for r in fold_outline(read_jsonl(project_path(root, OUTLINE_FILE))) if int(r.get("chapter") or 0) < chapter]
    lines = []
    for r in rows[-limit:]:
        beats = [str(x) for x in (r.get("beats") or []) if str(x).strip()]
        if beats:
            lines.append(f"第{r.get('chapter')}章《{r.get('title') or ''}》：{' / '.join(beats[:4])}")
    return "\n".join(lines) or "（暂无）"


def _extract_outline_json(text: str) -> dict[str, Any] | None:
    s = strip_fence(text or "")
    m = re.search(r"<<<OUTLINE_JSON([\s\S]*?)OUTLINE_JSON>>>", s)
    blob = m.group(1) if m else s
    start, end = blob.find("{"), blob.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(blob[start:end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _detail_messages(
    project: dict[str, Any],
    bible: dict[str, Any],
    *,
    root: str | os.PathLike,
    chapter: int,
    volume_block: str,
    volume: dict[str, Any] | None,
    stage: dict[str, Any] | None,
    recent: str,
    batch_to: int | None = None,
    prev_tail: str | None = None,
    foreshadow_this: str | None = None,
    foreshadow_rest: str | None = None,
    style_override: Any = None,
    focus: Any = None,
) -> list[dict[str, str]]:
    total = int(project.get("targetChapters") or 0)
    is_batch = bool(batch_to and int(batch_to) > chapter)
    batch_end = int(batch_to) if is_batch and batch_to is not None else chapter
    batch_count = batch_end - chapter + 1
    skills = read_skills(project)
    pack = build_reference_pack(root, chapter, focus=focus, stage="outline", skills=skills)
    style_text = _style_text(
        bible, project, style_override, stage="outline",
        samples=skills.get("styleSamples", True),
    )
    focus_text = _focus_block(focus)
    vol_head = f"，位于「{volume.get('title')}」（第{volume.get('from')}-{volume.get('to')}章）" if volume else ""
    # 提示词与「本章资料」面板必须同源：统一用 pack 里的截断结果。
    volume_outline = _section_text(pack, "volume-outline") or volume_block
    stage_body = _section_text(pack, "stage")
    stage_block = f"【本章所在台阶】\n{stage_body}" if stage_body else ""

    prev_tail_text = _section_text(pack, "prev-tail")
    foreshadow_this = _section_text(pack, "foreshadow-this")
    foreshadow_rest = _section_text(pack, "foreshadow-open")
    foreshadow_title = "【本批伏笔日程（按章分配节拍）】" if is_batch else "【本章伏笔（已按账本算好）】"
    foreshadow_body = (
        _foreshadow_schedule(root, chapter, batch_end) if is_batch
        else (foreshadow_this or "（本章没有到期/应埋的伏笔；可从下面挑一条续一笔，也可不埋）")
    )
    chars = _section_text(pack, "characters") or "（未登记人物卡）"
    state = _section_text(pack, "character-state") or "（还没有人物状态记忆）"
    relations = _section_text(pack, "relations") or "（还没有关系变化）"
    cont_state = _section_text(pack, "continuity-state") or "（还没有位置轨迹/转手记录）"
    gaps = _section_text(pack, "info-gaps") or "（还没有登记信息差）"
    rules = _section_text(pack, "rules") or "（无）"
    world = _section_text(pack, "world") or "（无）"
    factions = _section_text(pack, "factions") or "（无）"
    locations = _section_text(pack, "locations") or "（无）"
    items = _section_text(pack, "items") or "（无）"
    power = _section_text(pack, "power-system") or "（无）"
    society = _section_text(pack, "society") or "（无）"
    history = _section_text(pack, "history") or "（无）"
    glossary = _section_text(pack, "glossary") or "（无）"
    continuity_text = _section_text(pack, "continuity")
    chapter_memory = _section_text(pack, "chapter-memory") or "（最近几章还没有记忆）"
    volume_memory_text = _section_text(pack, "volume-memory") or "（前面各卷还没做卷摘要）"
    timeline = _section_text(pack, "timeline") or "（还没有故事内时间记录）"

    continuity = _skill_modules(root, skills, ("continuity",))
    continuity_block = f"【连续性方法（技能已开）】\n{continuity}\n" if continuity else ""
    continuity_facts = (
        f"【连贯性（事实层，不得违反）】\n{continuity_text}\n" if continuity_text else ""
    )
    # 平台 / 虐文都取 pack 的段落：面板显示什么，提示词就注入什么；关掉就不出现。
    platform_text = _section_text(pack, "platform")
    platform_block = f"【平台打法】\n{platform_text}\n" if platform_text else ""
    nuewen_text = _section_text(pack, "nuewen")
    nuewen = ""
    if nuewen_text:
        nuewen = f"""
【虐文原则（必须落进本章结构）】
{nuewen_text}
- 先立「最」：这一章要推进的是哪个角色最珍视的东西，具体到物件/习惯/话。
- 反转由他的选择推动：性格 → 压力下的选择 → 代价落地；写损失，不写「气氛沉重」。
"""

    if is_batch:
        output_spec = f"""【输出（硬要求）】
只输出一个 JSON 对象，不要解释、不要 Markdown 代码块：
{{"from":{chapter},"to":{batch_end},"spine":"这一批的因果一句话","chapters":[
{{"chapter":{chapter},"title":"≤12字标题","beats":["拍1：谁→想要→受阻→结果","拍2：…","拍3：…"],"mustInclude":["必须写到点"],"mustAvoid":["要避免的"],"openingState":"本章开场必须接上的上章状态（具体地点）","endingState":"本章结束时人物在哪、谁欠谁、留下什么悬念","pressure":{{"deadline":"还剩多久","stake":"不做会立刻失去什么","opponent":"谁在逼"}}}},
…第 {chapter + 1} 章到第 {batch_end} 章依此类推，一章一条…
]}}

硬性要求：
- chapters 必须按章号顺序完整覆盖第 {chapter}–{batch_end} 章，一章一条，不许多也不许少；
- 每章 3–6 拍，每拍：谁·在哪儿 → 想要什么 → 被什么挡住 → 结果变成什么；每章必须含主角一个决定及其代价；
- 第 k 章的 openingState 必须等于第 k-1 章的 endingState；第 {chapter} 章接上一章结尾；
- 每章收在本章并留钩子，不把下一章的内容提前写完；
- 整批只推进本批的「目标→转折」，不提前消费后面的卷情节。"""
    else:
        output_spec = f"""【输出顺序（硬要求）】
先输出机器块，必须完整：
<<<OUTLINE_JSON
{{"chapter":{chapter},"title":"≤12字标题","beats":["拍1：谁→想要→受阻→结果","拍2：…","拍3：…"],"mustInclude":["必须写到点"],"mustAvoid":["要避免的"],"openingState":"本章开场必须接上的上章状态（具体地点）","endingState":"本章结束时人物在哪、谁欠谁、留下什么悬念","pressure":{{"deadline":"还剩多久","stake":"不做会立刻失去什么","opponent":"谁在逼"}}}}
OUTLINE_JSON>>>

然后另起一行输出 Markdown 细纲：
## 1. 本章定位（章号 + 建议标题≤12字 / 本章目标一句话 / 本章高潮点哪一拍 / 结束状态）
## 2. 出场人物（只列真正出场的：名字 | 本章想要什么 | 结束时处境变化）
## 3. 节拍（3-6 拍，每拍：谁·在哪儿 → 想要什么 → 被什么挡住 → 结果变成什么 / 落点：读者情绪或信息变化。
   必须含主角的一个决定及其代价；写清「为什么此刻做」——他此刻得到什么，或不做会立刻失去什么（具体到钱、期限、病房、工作）。
   拍与拍因果递进；至少一拍障碍来自世界观规则；不要「思考/回忆/感慨」的独立一拍）
## 4. 必须出现（关键道具/信息/台词要点；本章要埋/要收的伏笔：名称+在哪一拍+怎么落）
## 5. 必须回避（不得使用的表达或桥段；不得出现的角色或信息；不得新增的设定或能力）
## 6. 章末钩子（三种写法各一：信息型 / 危险型 / 选择型）
## 7. 动机三件套（期限 / 代价 / 谁在逼）

硬性要求：每拍都能回答「为什么是现在」；不写正文、不写对话样例和景物；本章收在本章，不安排下一章。
位置连续性：拍1地点必须等于上一章收尾状态或 openingState 写明的地点；每拍换地点都要写「离开 A 去了 B」；
openingState / endingState 都要写具体地点（如「打铁铺门槛」），不能写「南街一线」这类范围。"""

    system = (
        "你是长篇网文的分批细纲编辑。你要把「这一批每章该发生什么」拆成可以直接照着写的节拍，"
        "并保证章与章之间用结束状态/开场状态衔接。你不写正文，不写对话样例，不写景物。"
        if is_batch else
        "你是长篇网文的章节设计编辑。你要把「这一章该发生什么」拆成可以直接照着写的节拍。"
        "你不写正文，不写对话样例，不写景物。"
    )
    range_head = (
        f"【本批】第 {chapter}–{batch_end} 章（共 {batch_count} 章）"
        if is_batch else f"【本章】第 {chapter} 章"
    )
    user = f"""{focus_text}{range_head} / 全书共 {total or '?'} 章{vol_head}
【上一章结尾（只作衔接，不要复述）】
{prev_tail_text or ('（开篇，没有上一章）' if chapter == 1 else '（上一章还没写，按已排细纲接上）')}

【本卷大纲切片】
{volume_outline}

{stage_block}

{foreshadow_title}
{foreshadow_body}

【其他在账未收伏笔（供参考，不必强行用）】
{foreshadow_rest or '（无）'}

【人物卡】
{chars}

【角色状态（人物当前状态，截至上一章）】
{state}

【人物关系】
{relations}

【位置轨迹与转手（截至上一章）】
{cont_state}

【信息差（谁瞒着谁、谁知道、谁不知道）】
{gaps}

【规则（铁律只能绕；契约可破但当场付代价；惯例违反有社会后果；谣言可被打破）】
{rules}

【世界观】
{world}

【势力】
{factions}

【地点】
{locations}

【物品】
{items}

【力量体系（等级、晋升、代价、上限；本章用到时必须守住）】
{power}

【社会常识（政治/经济/律法/禁忌/风俗，用来写环境和人情往来）】
{society}

【大事记（只作背景，不当场解释）】
{history}

【术语表（叫法必须统一，不要同物异名）】
{glossary}

【近章记忆（写新章必须接上）】
{chapter_memory}

【前面各卷摘要】
{volume_memory_text}

【故事内时间线】
{timeline}

【已排细纲（避免重复，要衔接）】
{recent}

{platform_block}【文风（本批实际生效）】
{style_text}

{continuity_facts}{continuity_block}{nuewen}
{output_spec}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _prose_messages(
    project: dict[str, Any],
    bible: dict[str, Any],
    *,
    root: str | os.PathLike,
    chapter: int,
    outline: dict[str, Any],
    prev_tail: str | None = None,
    style_override: Any = None,
    focus: Any = None,
) -> list[dict[str, str]]:
    rules = platform_rules(project.get("platform"))
    try:
        target = int(project.get("wordsPerChapter") or 0)
    except (TypeError, ValueError):
        target = 0
    if not target:
        target = int((int(rules.get("wordsMin") or 1500) + int(rules.get("wordsMax") or 5000)) / 2)
    lo, hi = int(rules.get("wordsMin") or 1200), int(rules.get("wordsMax") or 5000)
    skills = read_skills(project)
    pack = build_reference_pack(root, chapter, focus=focus, stage="prose", skills=skills)
    style_text = _style_text(
        bible, project, style_override, stage="prose",
        samples=skills.get("styleSamples", True),
    )
    focus_text = _focus_block(focus)
    beats = "\n".join(f"- {x}" for x in (outline.get("beats") or []))
    must = "\n".join(f"- {x}" for x in (outline.get("mustInclude") or []))
    avoid = "\n".join(f"- {x}" for x in (outline.get("mustAvoid") or []))
    pressure = outline.get("pressure") if isinstance(outline.get("pressure"), dict) else {}
    title = outline.get("title") or f"第{chapter}章"

    prev_tail_text = _section_text(pack, "prev-tail") or (prev_tail or "")
    chars = _section_text(pack, "characters") or "（未登记人物卡）"
    state = _section_text(pack, "character-state") or "（还没有人物状态记忆）"
    relations = _section_text(pack, "relations") or "（还没有关系变化）"
    cont_state = _section_text(pack, "continuity-state") or "（还没有位置轨迹/转手记录）"
    gaps = _section_text(pack, "info-gaps") or "（还没有登记信息差）"
    rules_text = _section_text(pack, "rules") or "（无）"
    world = _section_text(pack, "world") or "（无）"
    factions = _section_text(pack, "factions") or "（无）"
    locations = _section_text(pack, "locations") or "（无）"
    items = _section_text(pack, "items") or "（无）"
    power = _section_text(pack, "power-system") or "（无）"
    society = _section_text(pack, "society") or "（无）"
    history = _section_text(pack, "history") or "（无）"
    glossary = _section_text(pack, "glossary") or "（无）"
    volume_outline = _section_text(pack, "volume-outline")
    stage_body = _section_text(pack, "stage")
    foreshadow_this = _section_text(pack, "foreshadow-this")
    foreshadow_rest = _section_text(pack, "foreshadow-open")
    continuity_text = _section_text(pack, "continuity")
    chapter_memory = _section_text(pack, "chapter-memory") or "（最近几章还没有记忆）"
    volume_memory_text = _section_text(pack, "volume-memory") or "（前面各卷还没做卷摘要）"
    timeline = _section_text(pack, "timeline") or "（还没有故事内时间记录）"

    platform_text = _section_text(pack, "platform")
    platform_block = f"【平台打法（必须遵守）】\n{platform_text}\n" if platform_text else ""
    nuewen_text = _section_text(pack, "nuewen")
    nuewen = _nuewen_block(nuewen_text) if nuewen_text else ""
    methods = _skill_modules(root, skills, ("scene", "dialogue", "hook", "continuity"))
    methods_block = f"【写作方法（按技能开关注入）】\n{methods}\n\n" if methods else ""
    continuity_facts = (
        f"【连贯性（事实层，不得违反）】\n{continuity_text}\n" if continuity_text else ""
    )

    system = (
        "你是这部连载小说的作者本人，正在写第 "
        f"{chapter} 章。只输出本章正文：不要标题、不要章节号、不要说明、不要 Markdown 代码块。"
        "按细纲写足戏，场景、动作、对话都要落地，不要把一拍戏一笔带过。"
    )
    user = f"""{focus_text}【作品】{project.get('title') or ''}｜{project.get('genre') or ''}｜{project.get('tone') or ''}
【一句话】{project.get('logline') or ''}
{platform_block}{nuewen}
【本章】第{chapter}章《{title}》
建议字数：{target} 字（平台区间 {lo}-{hi} 字），写不到 {max(600, int(target * 0.75))} 字算不合格。

【本卷大纲切片（只定方向，不照抄）】
{volume_outline or '（本卷还没有大纲切片）'}

【本章在段落纲里的位置（方向参考，以细纲节拍为准）】
{stage_body or '（这一章还没排进段落纲）'}

【细纲·节拍】
{beats or '（没有节拍，按下面必须出现写）'}

【本章必须出现】
{must or '—'}

【本章必须回避】
{avoid or '—'}

【开场状态】{outline.get('openingState') or '—'}
【结束状态】{outline.get('endingState') or '—'}
【动机三件套】期限：{pressure.get('deadline') or '—'}｜代价：{pressure.get('stake') or '—'}｜谁在逼：{pressure.get('opponent') or '—'}

【本章伏笔（按账本算好：该埋的写进对应拍子，该收的当场收）】
{foreshadow_this or '（本章没有到期/应埋的伏笔；可从下面挑一条续一笔，也可不埋）'}

【其他在账未收伏笔（只作提醒，不要强行解释）】
{foreshadow_rest or '（无）'}

【人物卡】
{chars}

【角色状态（人物当前状态，截至上一章）】
{state}

【人物关系】
{relations}

【位置轨迹与转手（截至上一章）】
{cont_state}

【信息差（谁瞒着谁、谁知道、谁不知道）】
{gaps}

【规则（铁律只能绕；契约可破但当场付代价；惯例违反有社会后果；谣言可被打破）】
{rules_text}

【世界观】
{world}

【势力】
{factions}

【地点】
{locations}

【物品】
{items}

【力量体系（等级、晋升、代价、上限；本章用到时必须守住）】
{power}

【社会常识（政治/经济/律法/禁忌/风俗，用来写环境和人情往来）】
{society}

【大事记（只作背景，不当场解释）】
{history}

【术语表（叫法必须统一，不要同物异名）】
{glossary}

【近章记忆（写新章必须接上）】
{chapter_memory}

【前面各卷摘要】
{volume_memory_text}

【故事内时间线】
{timeline}

【文风（本批实际生效）】
{style_text}

【上一章结尾（只作衔接，不要复述）】
{prev_tail_text or '（本章是开篇）'}

{methods_block}{continuity_facts}
【写法】
1. 开场第一段直接接上一章收尾的地点/动作，不做前情回顾；回忆章按细纲从当下的入口进入回忆。
2. 每一拍写成具体场景：谁在哪儿、做了什么、说了什么、结果变成什么；不要用旁白概括。
3. 情绪用动作、停顿、重复细节承载；不写「他很难过」「气氛紧张」这类总结句。
4. 对话推进信息，人物口吻贴人物卡；单段不要过长。
5. 章末按细纲的钩子收，不要用旁白预告下一章。
6. 只写本章，不越过 endingState 往后写。
7. 允许写回忆 / 倒叙：先用当下的人、动作或物件做入口，交代清楚「这是什么时候、谁在回忆」，
   回忆结束回到现在。回忆里的时间、地点、人物状态按当时的写，不要和现在的时间线混在一起，
   也不要让回忆里的移动变成人物此刻的位置。
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _strip_chapter_head(text: str, title: str) -> str:
    s = strip_fence(text).strip()
    lines = s.splitlines()
    if lines:
        head = lines[0].strip().lstrip("#").strip()
        if head == title or re.match(r"^第\s*[0-9一二三四五六七八九十百零]+\s*章", head):
            s = "\n".join(lines[1:]).strip()
    return s


def _write_outline(
    root: str | os.PathLike,
    chapter: int,
    outline: dict[str, Any],
    detail: str,
    model: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "chapter": chapter,
        "title": str(outline.get("title") or ""),
        "beats": [str(x) for x in (outline.get("beats") or []) if str(x).strip()],
        "mustInclude": [str(x) for x in (outline.get("mustInclude") or []) if str(x).strip()],
        "mustAvoid": [str(x) for x in (outline.get("mustAvoid") or []) if str(x).strip()],
        "openingState": str(outline.get("openingState") or ""),
        "endingState": str(outline.get("endingState") or ""),
        "pressure": outline.get("pressure") if isinstance(outline.get("pressure"), dict) else {},
        "detail": detail,
        "source": "ai",
        "model": model,
        "at": _now(),
    }
    if extra:
        row.update(extra)
    append_jsonl(project_path(root, OUTLINE_FILE), row)
    return row


def _outline_detail(row: dict[str, Any]) -> str:
    """批次细纲没有逐章 Markdown 原文，按结构化字段补一份可读文本。"""
    lines = [f"## 第{row['chapter']}章《{row.get('title') or ''}》", "", "### 节拍"]
    lines += [f"- {x}" for x in (row.get("beats") or [])]
    if row.get("mustInclude"):
        lines += ["", "### 必须出现"] + [f"- {x}" for x in row["mustInclude"]]
    if row.get("mustAvoid"):
        lines += ["", "### 必须回避"] + [f"- {x}" for x in row["mustAvoid"]]
    lines += ["", f"开场：{row.get('openingState') or '—'}"]
    lines += [f"结束：{row.get('endingState') or '—'}"]
    pressure = row.get("pressure") if isinstance(row.get("pressure"), dict) else {}
    if pressure:
        bits = [f"{k}：{v}" for k, v in pressure.items() if v]
        if bits:
            lines += [f"压力：{'；'.join(bits)}"]
    return "\n".join(lines)


def _resolve_chapter(root: str | os.PathLike, number: int | None) -> int:
    index = read_index(root)
    numbers = [int(c.get("number") or 0) for c in index]
    return int(number or (max(numbers) + 1 if numbers else 1))


def _assert_chapter_range(project: dict[str, Any], chapter: int) -> None:
    if chapter <= 0:
        raise ChapterOutOfRange("章号必须是正整数")
    target = int(project.get("targetChapters") or 0)
    if target and chapter > target:
        raise ChapterOutOfRange(f"章号超出全书范围（共 {target} 章）：第 {chapter} 章")


def _usable_outline(row: Any) -> bool:
    return isinstance(row, dict) and bool([x for x in (row.get("beats") or []) if str(x).strip()])


def generate_outline(
    root: str | os.PathLike,
    *,
    number: int | None = None,
    model: str | None = None,
    force: bool = False,
    style_override: Any = None,
    focus: Any = None,
    reuse_outline: bool = True,
    skills_override: Any = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """只生成细纲。已有可用细纲且 force=False → reused，不调模型。"""
    project = _apply_skill_override(_project(root), skills_override)
    outline_text = str(project.get("outlineText") or "").strip()
    if not outline_text:
        raise NoOutlineError("还没有大纲：先在「开书」页生成大纲+世界观，再写正文")
    chapter = _resolve_chapter(root, number)
    _assert_chapter_range(project, chapter)
    bible = load_bible(root)
    applied = style_mod.style_applied(bible.get("style"), project.get("platform"), style_override)

    existing = _outline_row(root, chapter) if reuse_outline else None
    if _usable_outline(existing) and not force:
        return {
            "ok": True,
            "chapter": chapter,
            "outline": existing,
            "styleApplied": applied,
            "model": str(existing.get("model") or ""),
            "reused": True,
        }

    volumes = load_volumes(root)
    volume_block, volume = _volume_slice(outline_text, volumes, chapter)
    stage = _stage_for(root, chapter)
    recent = _recent_outlines(root, chapter)

    if on_stage:
        on_stage("写本章细纲")
    result = chat(
        _detail_messages(
            project, bible,
            root=root, chapter=chapter, volume_block=volume_block, volume=volume, stage=stage,
            recent=recent, style_override=style_override, focus=focus,
        ),
        model=model, temperature=0.6, max_tokens=6000, timeout=480, reasoning=reasoning_for("outline"),
        on_delta=on_delta,
    )
    if on_stage:
        on_stage("整理节拍")
    detail_text = str(result.get("text") or "")
    outline_model = str(result.get("model") or "")
    parsed = _extract_outline_json(detail_text)
    if not parsed or not isinstance(parsed.get("beats"), list) or not [x for x in parsed["beats"] if str(x).strip()]:
        raise LLMError(f"第{chapter}章细纲没有返回可解析的节拍。原文片段：{detail_text[:200]}")
    parsed["chapter"] = chapter
    # 正文里去掉机器块，只留 Markdown 细纲
    clean_detail = re.sub(r"<<<OUTLINE_JSON[\s\S]*?OUTLINE_JSON>>>", "", detail_text).strip()
    row = _write_outline(root, chapter, parsed, clean_detail, outline_model)
    _record_usage(root, {
        "kind": "outline", "chapter": chapter,
        "tokens": int(result.get("usage", {}).get("total_tokens") or estimate_tokens(detail_text)),
        "model": outline_model,
    })
    return {
        "ok": True,
        "chapter": chapter,
        "outline": row,
        "styleApplied": applied,
        "model": outline_model,
        "reused": False,
    }


def generate_outlines(
    root: str | os.PathLike,
    *,
    frm: int | None = None,
    to: int | None = None,
    model: str | None = None,
    force: bool = False,
    style_override: Any = None,
    focus: Any = None,
    skills_override: Any = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """一批章节共用一次模型调用出细纲：每章一条，章与章按 ending→opening 衔接。

    这是写作流程的默认粒度。已有整批可用细纲且 force=False 时直接复用，不调模型。
    """
    project = _apply_skill_override(_project(root), skills_override)
    outline_text = str(project.get("outlineText") or "").strip()
    if not outline_text:
        raise NoOutlineError("还没有大纲：先在「开书」页生成大纲+世界观，再写正文")

    start = _resolve_chapter(root, frm)
    end = int(to or start)
    target = int(project.get("targetChapters") or 0)
    if target:
        end = min(end, target)
    if end < start:
        end = start
    _assert_chapter_range(project, start)
    _assert_chapter_range(project, end)

    bible = load_bible(root)
    applied = style_mod.style_applied(bible.get("style"), project.get("platform"), style_override)

    numbers = list(range(start, end + 1))
    existing = {n: _outline_row(root, n) for n in numbers}
    if not force and all(_usable_outline(existing[n]) for n in numbers):
        return {
            "ok": True,
            "from": start,
            "to": end,
            "outlines": [existing[n] for n in numbers],
            "styleApplied": applied,
            "model": "",
            "reused": True,
        }

    volumes = load_volumes(root)
    volume_block, volume = _volume_slice(outline_text, volumes, start)
    stage = _stage_for(root, start)
    recent = _recent_outlines(root, start)

    if on_stage:
        on_stage(f"写第 {start}–{end} 章细纲")
    result = chat(
        _detail_messages(
            project, bible,
            root=root, chapter=start, batch_to=end,
            volume_block=volume_block, volume=volume, stage=stage,
            recent=recent, style_override=style_override, focus=focus,
        ),
        model=model, temperature=0.6,
        max_tokens=max(6000, min(32000, 2200 * len(numbers))),
        timeout=900, reasoning=reasoning_for("outline"),
        on_delta=on_delta,
    )
    if on_stage:
        on_stage("整理节拍")

    detail_text = str(result.get("text") or "")
    outline_model = str(result.get("model") or "")
    parsed = _extract_outline_json(detail_text)
    chapters = parsed.get("chapters") if isinstance(parsed, dict) else None
    if not isinstance(chapters, list):
        raise LLMError(f"批次细纲没有返回 chapters。原文片段：{detail_text[:200]}")

    by_num: dict[int, dict[str, Any]] = {}
    for item in chapters:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("chapter"))
        except (TypeError, ValueError):
            continue
        if start <= n <= end and _usable_outline(item):
            by_num[n] = item
    missing = [n for n in numbers if n not in by_num]
    if missing:
        joined = "、".join(str(n) for n in missing)
        raise LLMError(f"批次细纲缺第 {joined} 章；原文片段：{detail_text[:200]}")

    spine = str(parsed.get("spine") or "")
    extra = {"batchFrom": start, "batchTo": end, "batchSpine": spine}
    rows: list[dict[str, Any]] = []
    for n in numbers:
        item = {**by_num[n], "chapter": n}
        row = _write_outline(
            root, n, item, _outline_detail(item), outline_model, extra=extra,
        )
        rows.append(row)
    _record_usage(root, {
        "kind": "outline-batch", "from": start, "to": end,
        "tokens": int(result.get("usage", {}).get("total_tokens") or estimate_tokens(detail_text)),
        "model": outline_model,
    })
    return {
        "ok": True,
        "from": start,
        "to": end,
        "outlines": rows,
        "spine": spine,
        "styleApplied": applied,
        "model": outline_model,
        "reused": False,
    }


def generate_prose(
    root: str | os.PathLike,
    *,
    number: int,
    model: str | None = None,
    overwrite: bool = False,
    style_override: Any = None,
    focus: Any = None,
    outline: dict[str, Any] | None = None,
    skills_override: Any = None,
    candidates: int = 1,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """照细纲写正文；失败时不落任何正文。

    ``candidates`` >1 时并排写几稿再按确定性指标挑一稿（流式不支持，自动按 1 稿）。
    多稿会多花模型调用，默认仍然是 1。
    """
    project = _apply_skill_override(_project(root), skills_override)
    chapter = int(number)
    _assert_chapter_range(project, chapter)

    existing = read_index_entry(root, chapter)
    if existing and not overwrite:
        raise ChapterExists(f"第{chapter}章已经有正文；要重写请先退回，或勾选覆盖")

    outline_row = outline if _usable_outline(outline) else _outline_row(root, chapter)
    if not _usable_outline(outline_row):
        raise NoOutlineRow(f"第{chapter}章还没有细纲，先点「生成细纲」")

    # 伏笔是正文的骨架：一条都没有时不放行，否则写出去的情节无处回收。
    if not fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE))):
        raise NoForeshadowError(
            f"第{chapter}章还不能写正文：先在「开书 → 伏笔」设计至少一条伏笔，正文要按伏笔网推进"
        )

    bible = load_bible(root)
    applied = style_mod.style_applied(bible.get("style"), project.get("platform"), style_override)

    prose_messages = _prose_messages(
        project, bible, root=root, chapter=chapter, outline=outline_row,
        style_override=style_override, focus=focus,
    )
    title = str(outline_row.get("title") or f"第{chapter}章").strip()
    try:
        target = int(project.get("wordsPerChapter") or 0)
    except (TypeError, ValueError):
        target = 0
    if not target:
        rules = platform_rules(project.get("platform"))
        target = int(rules.get("wordsMin") or 1500)

    # 流式只能推一稿；非流式才可以多写几稿再挑。
    rounds = max(1, min(3, int(candidates or 1))) if on_delta is None else 1
    drafts: list[tuple[str, dict[str, Any]]] = []
    for i in range(rounds):
        if on_stage:
            on_stage(f"写正文（第 {i + 1}/{rounds} 稿）" if rounds > 1 else "写正文")
        result = chat(
            prose_messages,
            model=model, temperature=0.85, max_tokens=14000, timeout=600, reasoning=reasoning_for("prose"),
            on_delta=on_delta if i == 0 else None,
        )
        drafts.append((_strip_chapter_head(str(result.get("text") or ""), title), result))
    if len(drafts) > 1:
        text, prose = max(drafts, key=lambda d: _prose_candidate_score(d[0], target))
        if on_stage:
            on_stage(f"已从 {len(drafts)} 稿里挑了一稿")
    else:
        text, prose = drafts[0]
    chars = count_chars(text)

    # 模型常把 2000 字的目标写成 1500 字；低于目标 85% 时补一次「写完整版」，
    # 而不是把半成品直接落盘让体检再打回。只补一次，避免无限加长。
    if chars < int(target * 0.85):
        want = max(target, int(target * 1.05))
        if on_stage:
            on_stage(f"正文偏短（{chars} 字），正在补写")
        expand = chat(
            prose_messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"上一稿只有 {chars} 字，不够本章的字数要求（目标 {target} 字）。"
                    "请保留已经发生的情节事实和人物口吻，把这章重写成完整正文，"
                    f"补足场景、动作与对话，写到 {want} 字以上；不要说明、不要标题、不要复述上一稿。"
                )},
            ],
            model=model, temperature=0.8, max_tokens=16000, timeout=600, reasoning=reasoning_for("prose"),
        )
        longer = _strip_chapter_head(str(expand.get("text") or ""), title)
        if count_chars(longer) > chars:
            text = longer
            chars = count_chars(longer)
            prose = expand

    if chars < 300:
        raise ProseTooShort(f"第{chapter}章正文过短（{chars} 字），未落盘；可以重试或换模型")

    at = _now()
    backup_draft = ""
    with project_lock(root):
        current = _project(root)
        entry = read_index_entry(root, chapter)
        if entry:
            ensure_dir(project_path(root, LAYOUT["drafts"]))
            old = read_chapter(root, chapter) or ""
            if old.strip():
                draft = f"{LAYOUT['drafts']}/{pad3(chapter)}-{_safe(entry.get('title'), '未命名')}-replace-{int(datetime.now().timestamp() * 1000):x}.md"
                project_path(root, draft).write_text(old, encoding="utf-8")
                append_jsonl(project_path(root, REVIEW_FILE), {
                    "kind": "rewrite",
                    "number": chapter,
                    "title": entry.get("title") or "",
                    "reason": "AI 重新生成前的自动备份",
                    "draftFile": draft,
                    "at": at,
                })
                backup_draft = draft
        _, rel = write_chapter_file(root, chapter, title, text)
        row = _entry_from_text({
            "number": chapter,
            "title": title,
            "file": rel,
            "summary": clamp_summary(text, 240),
            "characters": characters_mentioned(bible, text),
            "approved": False,
            "approvedAt": "",
            "source": "ai",
            "generatedAt": at,
        }, text)
        row["committedAt"] = at
        add_to_index(root, row)

        # 补生成旧章时 chapter+1 可能早已写过；下一章永远取索引最大章 + 1。
        current["currentChapter"] = written_through(root)
        next_chapter = current["currentChapter"] + 1
        current["gate"] = {
            "phase": "awaiting_review",
            "chapter": next_chapter,
            "reason": f"第{chapter}章已生成，待你在进度页确认",
            "at": at,
        }
        current["updatedAt"] = at
        save_project(root, current)

    _record_usage(root, {
        "kind": "write", "chapter": chapter, "chars": chars,
        "tokens": int(prose.get("usage", {}).get("total_tokens") or estimate_tokens(text)),
        "model": str(prose.get("model") or ""),
    })
    if on_stage:
        on_stage("回写记忆")
    result = {
        "ok": True,
        "chapter": read_index_entry(root, chapter),
        "text": text,
        "chars": chars,
        "styleApplied": applied,
        "candidates": rounds,
        "model": str(prose.get("model") or ""),
        "memory": _auto_write_back(root, chapter, force=bool(existing)),
    }
    if backup_draft:
        result["backupDraft"] = backup_draft
    return result


def generate_chapter(
    root: str | os.PathLike,
    *,
    number: int | None = None,
    model: str | None = None,
    overwrite: bool = False,
    reuse_outline: bool = True,
    style_override: Any = None,
    focus: Any = None,
    skills_override: Any = None,
) -> dict[str, Any]:
    """兼容包装：先细纲后正文；错误仍以 ``ValueError`` 暴露给旧调用方。"""
    project = _project(root)
    chapter = _resolve_chapter(root, number)
    if chapter <= 0:
        raise ValueError("章号必须是正整数")
    existing = read_index_entry(root, chapter)
    if existing and not overwrite:
        raise ValueError(f"第{chapter}章已经有正文；要重写请先退回，或勾选覆盖")
    try:
        outline_res = generate_outline(
            root, number=chapter, model=model, force=False,
            style_override=style_override, focus=focus, reuse_outline=reuse_outline,
            skills_override=skills_override,
        )
        prose_res = generate_prose(
            root, number=chapter, model=model, overwrite=overwrite,
            style_override=style_override, focus=focus, outline=outline_res["outline"],
            skills_override=skills_override,
        )
    except (ChapterExists, ChapterOutOfRange, NoOutlineError, NoOutlineRow, ProseTooShort) as e:
        raise ValueError(str(e)) from e
    return {
        "ok": True,
        "chapter": prose_res["chapter"],
        "outline": outline_res["outline"],
        "text": prose_res["text"],
        "chars": prose_res["chars"],
        "model": prose_res["model"],
        "outlineModel": outline_res["model"],
        "memory": prose_res.get("memory"),
    }


def _safe(value: Any, fallback: str) -> str:
    s = re.sub(r"[/\\:*?\"<>|]+", "_", str(value or "")).strip().strip(".")
    return s[:60] or fallback


def _record_usage(root: str | os.PathLike, row: dict[str, Any]) -> None:
    append_jsonl(project_path(root, USAGE_FILE), {"at": _now(), **row})


def _auto_write_back(root: str | os.PathLike, chapter: int, *, force: bool = False) -> dict[str, Any]:
    """正文落盘后让 AI 回写这一章的记忆；失败只报告，不回滚正文。"""
    try:
        from . import memory_gen

        return memory_gen.auto_write_back(root, chapter, force=force)
    except Exception as e:  # noqa: BLE001 — 记忆是派生数据，不能拖垮写作
        return {"ok": False, "error": str(e)}
