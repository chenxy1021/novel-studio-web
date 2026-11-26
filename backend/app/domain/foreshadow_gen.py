"""开书第四步：由「大纲 + 世界观 + 设定」设计整套伏笔（草蛇灰线）。

对应旧插件 foreshadow-gen：
- 伏笔必须来自已有的规则 / 人物 / 地点 / 势力 / 物品，或有明确的来源；
- 重要伏笔不能只埋一次，中途要「不经意再露一次」；
- 回收章必须晚于埋设章，核心/卷级不能埋完一两章就收；
- 一次铺满全书，按卷分配，不挤在最近几章。
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from ..store import append_jsonl, load_bible, load_project, project_lock, project_path, read_jsonl, save_project, written_through
from ..store.jsonl import fold_foreshadow
from .memory import load_volumes

FORESHADOW_FILE = "ledger/foreshadow.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _num(value: Any) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _name_key(value: Any) -> str:
    return re.sub(r"[\s·・\-—_/、，,。.（）()「」『』【】]+", "", str(value or "")).lower()


def _name_taken(key: str, seen: set[str]) -> bool:
    """同名，或者只是给已有线加了个后缀（「五点四十就到了」vs「…却从不进登记室」）。

    AI 补伏笔时爱把旧线换个说法再写一遍，账本多两条一模一样的线，体检就会催作者
    收两条收不掉的伏笔。短的至少 4 个字才做包含判断，避免误杀。
    """
    if not key:
        return True
    if key in seen:
        return True
    return any(len(k) >= 4 and (key in k or k in key) for k in seen)


def _slot(name: Any, kind: Any, planted: Any, due: Any) -> dict[str, Any]:
    return {
        "name": _name_key(name),
        "kind": str(kind or "detail"),
        "planted": int(planted or 0),
        "due": int(due or 0),
    }


def _same_line(row: dict[str, Any], other: dict[str, Any]) -> bool:
    """同一层级、埋收章相差不超过 1、名字至少四成字重合：当作同一条线换了个说法。

    AI 补伏笔会把「后窗插销锈死」写成「后窗插销被人从外面焊过」，名字既不相同也不
    互为前后缀，_name_taken 挡不住；埋收章几乎重合才是同一件事的硬信号。名字重合度
    用来避免把同一章里两条不同的线误杀。
    """
    if row["kind"] != other["kind"]:
        return False
    if abs(row["planted"] - other["planted"]) > 1:
        return False
    if row["due"] and other["due"] and abs(row["due"] - other["due"]) > 1:
        return False
    a, b = row["name"], other["name"]
    if not a or not b:
        return False
    common = len(set(a) & set(b))
    return common / max(1, min(len(a), len(b))) >= 0.4


def _clean_rows(bible: dict[str, Any]) -> str:
    def line(tag: str, rows: list[dict[str, Any]], fields: list[str]) -> str:
        out = []
        for row in rows[:60]:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            bits = [str(row.get(f) or "").strip() for f in fields]
            bits = [b for b in bits if b]
            out.append(f"【{tag}·{name}】" + "；".join(bits))
        return "\n".join(out)

    parts = [
        line("世界", bible.get("world") or [], ["text"]),
        line("势力", bible.get("factions") or [], ["text", "hiddenRules", "relations"]),
        line("地点", bible.get("locations") or [], ["text", "accessRules"]),
        line("规则", bible.get("rules") or [], ["text", "cost", "boundary"]),
        line("人物", bible.get("characters") or [], ["role", "want", "secret", "fear"]),
        line("物品", bible.get("items") or [], ["text", "holder", "state"]),
    ]
    return "\n".join(p for p in parts if p)


def build_messages(project: dict[str, Any], bible: dict[str, Any], existing: list[dict[str, Any]]) -> tuple[list[dict[str, str]], int, int]:
    outline = str(project.get("outlineText") or "").strip()
    world = str(project.get("worldText") or "").strip()
    if not outline:
        raise ValueError("还没有大纲：先在「开书」页生成大纲+世界观，再设计伏笔")
    try:
        total = int(project.get("targetChapters") or 0)
    except (TypeError, ValueError):
        total = 0
    current = int(project.get("currentChapter") or 0)
    volumes = load_volumes(str(project.get("_root") or "")) if project.get("_root") else []
    if not volumes:
        # 没有卷索引时按 50 章一卷估个量级，只用于配额
        volumes = [{"title": "", "from": 1, "to": total or 120}]
    volume_count = max(1, len(volumes))
    core = 3
    volume_fs = volume_count * 2
    plot_max = volume_count * 4
    planned = core + volume_fs + plot_max
    asked = max(6, min(200, planned))

    if len(outline) > 9000:
        outline = outline[:9000] + "\n…（大纲后段从略，按上面卷结构推断即可）"
    if len(world) > 4500:
        world = world[:4500] + "\n…（世界观后段从略）"

    existing_block = ""
    if existing:
        existing_block = "=== 已有伏笔（不要重复；新伏笔要能衔接）===\n" + "\n".join(
            f"{f.get('name')}｜{f.get('kind') or 'detail'}｜第{f.get('plantedChapter') or '?'}→{f.get('dueChapter') or '?'}章"
            for f in existing[:80]
        )

    vol_lines = "\n".join(
        f"- {v.get('title') or f'第{i + 1}卷'}：第 {v.get('from')}-{v.get('to')} 章"
        for i, v in enumerate(volumes)
    )

    system = "你是长篇网文的结构编辑。任务：在故事梗概、世界观、人物与设定、大纲已经定下的范围里，设计整套伏笔的埋设与揭晓计划。你只输出结构化数据，不写正文。"

    user = f"""【当前进度】第 {current} 章。{f'全书计划约 {total} 章、约 {volume_count} 卷。' if total else ''}

【卷结构】
{vol_lines}

【故事梗概】
{str(project.get('synopsis') or '').strip() or '（空）'}

【已有设定】
{_clean_rows(bible) or '（无）'}

{existing_block}

【世界观】
{world or '（空）'}

【大纲】
{outline}

【配额】
核心伏笔 {core} 条（贯穿全书、最后揭），卷级伏笔每卷 2 条共 {volume_fs} 条（在本卷区间内回收），
情节伏笔每卷 2-4 条（按需要取，不必凑满）。共约 {asked} 条。

【硬要求】
- 每条伏笔必须来自上面已有的一条规则 / 人物 / 地点 / 势力 / 物品，source 写成「类型·名字」，不许只写编号，没有来源的不许写。
- 回收章必须大于埋设章；核心伏笔回收章要比埋设章晚至少一整卷的跨度；卷级伏笔回收章 ≥ 埋设章 +5 且在同一卷内；情节伏笔可以埋收相邻。{f'所有回收章不超过第 {total} 章。' if total else ''}
- 埋设章从第 {current + 1} 章起，按卷往后铺，同一卷内大致均匀，不要全挤在最近几章。
- 草蛇灰线：一条重要伏笔不许只埋一次，中途至少在一两个间隔章里不经意地再露一次（人物提一句、物件换个地方、旁人一句闲话），写进「中途提示」；揭晓章才收。
- 细节伏笔优先用「读者第一遍看不出是伏笔」的东西：一个称呼、一个习惯动作、一件旧物、一句说反的话、一个没回答的问题、一处钱数/日期对不上。不许写成作者举着牌子埋伏笔。
- 伏笔要跟人物或主线有牵连：揭晓后改变了谁对谁的看法、谁的身份、哪条利益，或反过来解释了前面某个反常。只解释世界设定的伏笔最多占三成。
- 埋点要能被后续检到：plantBeat 写清具体的物件/台词/动作/地名，不要写「氛围」「暗示」。

【输出格式】一行一条，用竖线分隔，不要 JSON、不要表头、不要解释、不要代码块：
名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃
层次只写 主线/卷内/细节；文字列各控制在 20 字以内；埋设章和回收章必须是数字；名称各不相同。
共约 {asked} 条。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], asked, planned


def _parse_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in strip_fence(text).splitlines():
        line = raw.strip().strip("`")
        if not line or line.startswith("```"):
            continue
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6:
            continue
        name = cells[0]
        if not name or name in ("名称", "---") or set(name) <= {"-", "—"}:
            continue
        kind_raw = cells[1]
        kind = "main" if "主线" in kind_raw or kind_raw == "main" else "volume" if "卷内" in kind_raw or kind_raw == "volume" else "detail"
        plant = _num(cells[3])
        due = _num(cells[5])
        if not plant:
            continue
        rows.append({
            "name": name,
            "kind": kind,
            "source": cells[2],
            "plantChapter": plant,
            "plantBeat": cells[4],
            "dueChapter": due,
            "revealWho": cells[6] if len(cells) > 6 else "",
            "revealChange": cells[7] if len(cells) > 7 else "",
            "hint": cells[8] if len(cells) > 8 else "",
            "abandon": cells[9] if len(cells) > 9 else "",
        })
    return rows


def generate_foreshadows(
    root: str | os.PathLike,
    *,
    count: int | None = None,
    model: str | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    if not str(project.get("worldText") or "").strip():
        raise ValueError("还没有世界观：先在「开书」页生成大纲+世界观，再设计伏笔")
    bible = load_bible(root)
    existing = fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
    messages, asked, planned = build_messages({**project, "_root": str(root)}, bible, existing)
    if count and count > 0:
        asked = max(3, min(200, int(count)))

    if on_stage:
        on_stage("铺伏笔网")
    result = chat(
        messages, model=model, temperature=0.6, max_tokens=12000, timeout=480, reasoning=reasoning_for("foreshadow"),
        on_delta=on_delta,
    )
    text = str(result.get("text") or "")
    parsed = _parse_rows(text)
    if not parsed:
        # 格式不对 / 被截断时换一次请求重试，别让作者等了两分钟只拿到报错。
        if on_stage:
            on_stage("伏笔格式不对，重试")
        if on_delta:
            on_delta("\n\n── 重试 ──\n")
        result = chat(
            messages, model=model, temperature=0.5, max_tokens=12000, timeout=480, reasoning=reasoning_for("foreshadow"),
            on_delta=on_delta,
        )
        text = str(result.get("text") or "")
        parsed = _parse_rows(text)
    if not parsed:
        raise LLMError(f"模型没有返回可解析的伏笔（格式不对或被截断）。原文片段：{text[:200]}")

    if on_stage:
        on_stage("整理种子")

    try:
        total = int(project.get("targetChapters") or 0)
    except (TypeError, ValueError):
        total = 0

    seen = {_name_key(f.get("name")) for f in existing}
    slots = [
        _slot(f.get("name"), f.get("kind"), f.get("plantedChapter"), f.get("dueChapter"))
        for f in existing
        if f.get("name")
    ]
    written: list[dict[str, Any]] = []
    skipped = 0
    guarded = 0
    at = _now()
    with project_lock(root):
        for row in parsed[:220]:
            key = _name_key(row["name"])
            if _name_taken(key, seen):
                skipped += 1
                continue
            plant = int(row["plantChapter"])
            due = int(row.get("dueChapter") or 0)
            if total and plant > total:
                plant = max(1, total)
            if due and due <= plant:
                due = 0
            min_gap = 10 if row["kind"] == "main" else 5 if row["kind"] == "volume" else 1
            if due and due - plant < min_gap:
                pushed = plant + min_gap
                if not total or pushed <= total:
                    due = pushed
                    guarded += 1
                else:
                    due = 0
            if due and total and due > total:
                due = total if total > plant else 0
            slot = _slot(row["name"], row["kind"], plant, due)
            if any(_same_line(slot, old) for old in slots):
                skipped += 1
                continue
            record = {
                "id": f"fs-{uuid.uuid4().hex[:8]}",
                "name": row["name"],
                "kind": row["kind"],
                "plantedChapter": plant,
                "dueChapter": due or None,
                "status": "open",
                "source": row.get("source") or "AI 伏笔设计",
                "plantBeat": row.get("plantBeat") or "",
                "revealWho": row.get("revealWho") or "",
                "revealChange": row.get("revealChange") or "",
                "hint": row.get("hint") or "",
                "abandon": row.get("abandon") or "",
                "at": at,
            }
            append_jsonl(project_path(root, FORESHADOW_FILE), record)
            seen.add(key)
            slots.append(slot)
            written.append(record)

        current = load_project(root) or project
        current["foreshadowAt"] = at
        current["gate"] = {
            "phase": "planning",
            "chapter": max(1, written_through(root) + 1),
            "reason": "伏笔已经铺好，可以开始写第 1 章了",
            "at": at,
        }
        current["updatedAt"] = at
        save_project(root, current)

    return {
        "ok": True,
        "asked": asked,
        "planned": planned,
        "count": len(written),
        "skipped": skipped,
        "guarded": guarded,
        "rows": written,
        "model": str(result.get("model") or ""),
        "summary": f"设计并落账 {len(written)} 条伏笔"
        + (f"；同名跳过 {skipped} 条" if skipped else "")
        + (f"；回收章过近已推后 {guarded} 条" if guarded else ""),
    }
