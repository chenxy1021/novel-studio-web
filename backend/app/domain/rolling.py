"""滚动规划：书跑到原大纲尽头时，接着往下铺，而不是一次把全书想死。

三样东西：

1. **罗盘**（``project.compassText``）：作者自己写的一段方向——主角要什么、什么
   不能变、眼下最想写的冲突。每次规划都带上，防止越写越偏。
2. **补卷**：已写章号越过最后一卷的区间时，按罗盘 + 最近几章 + 已有卷的大纲，
   生成下一卷的卷头与大情节，追加到 ``project.outlineText``，并刷新卷索引。
3. **补细纲**：紧接着调用 ``writing.generate_outlines`` 生成下一批逐章节拍。

只追加、不重写：已有卷和已有细纲都不动；要改请走原来的「重生成细纲」。
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from ..store import (
    load_bible,
    load_project,
    project_lock,
    save_project,
    written_through,
)
from .memory import load_memory_rows, load_volumes, refresh_volumes
from .writing import generate_outlines

_VOL_HEAD = re.compile(r"^###\s*第\s*[0-9一二三四五六七八九十百千]+\s*卷", re.M)
_VOL_SPAN = re.compile(r"第\s*(\d{1,5})\s*[-–—~～至到]\s*(\d{1,5})\s*章")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    return project


def set_compass(root: str | os.PathLike, text: str) -> dict[str, Any]:
    """保存罗盘。空字符串等于清空（不再把方向塞进规划提示词）。"""
    at = _now()
    with project_lock(root):
        project = _project(root)
        project["compassText"] = _text(text)[:2000]
        project["compassAt"] = at
        project["updatedAt"] = at
        save_project(root, project)
    return {"ok": True, "compassText": project["compassText"], "at": at}


def _volume_material(root: str | os.PathLike, project: dict[str, Any], next_no: int) -> str:
    """补卷用的素材：罗盘、全书层大纲、已有卷、最近章节摘要、核心人物。"""
    outline = str(project.get("outlineText") or "")
    heads = [m.start() for m in _VOL_HEAD.finditer(outline)]
    # 全书层（第一个卷头之前）+ 最后一卷的正文
    overview = outline[:heads[0]] if heads else outline
    last_block = outline[heads[-1]:] if heads else ""
    memory = load_memory_rows(root)
    by_chapter = memory.get("byChapter") or {}
    recent = "\n".join(
        f"第{n}章：{_text((by_chapter.get(n) or {}).get('summary'))[:160]}"
        for n in sorted(by_chapter)[-6:]
    )
    bible = load_bible(root)
    chars = "；".join(
        f"{_text(c.get('name'))}（{_text(c.get('role') or c.get('rolePosition'))}；目标 {_text(c.get('want'))}）"
        for c in (bible.get("characters") or [])[:12]
        if _text(c.get("name"))
    )
    return "\n".join([
        f"下一卷是第 {next_no} 卷。",
        "",
        "【罗盘】",
        _text(project.get("compassText")) or "（作者没写罗盘，按全书大纲推进）",
        "",
        "【全书层】",
        overview[:3000] or "（无）",
        "",
        "【最后一卷】",
        last_block[:3000] or "（无）",
        "",
        "【最近六章】",
        recent or "（还没有章节记忆）",
        "",
        "【核心人物】",
        chars or "（无）",
    ])


def _volume_messages(root: str | os.PathLike, project: dict[str, Any], next_no: int) -> list[dict[str, str]]:
    try:
        target = int(project.get("targetChapters") or 0)
    except (TypeError, ValueError):
        target = 0
    written = written_through(root)
    system = "\n".join([
        "你是中文网文的连载策划。现在要接着往下规划新的一卷，只输出 Markdown。",
        "",
        "# 硬性要求",
        f"1. 卷头格式一字不差：### 第{next_no}卷 卷名（第a-b章）。卷名不超过 8 字；a 从 {written + 1} 开始。",
        "2. 这一卷必须完成一个完整的矛盾阶段：目标 → 升级 → 卷末不可逆变化；卷末要留下下一卷的钩子。",
        "3. 必须服从罗盘：主角的欲望、不能变的东西、作者眼下最想写的冲突，不能为了热闹跑偏。",
        "4. 承接最近几章的实际状态：谁在哪、谁欠谁、什么伏笔还开着，不能凭空重置。",
        "5. 不写人物卡、不写势力表、不写物品清单；只写这一卷的结构。",
        "6. 篇幅 800–1500 字，信息密度优先。章数由内容决定，不要为了凑数拉长。",
        "",
        "# 输出格式",
        f"### 第{next_no}卷 卷名（第{written + 1}-X章）",
        "- 任务与矛盾：……",
        "- 卷内节拍：3-5 拍，每拍写「谁做了什么 → 谁失去/得到什么」",
        "- 卷末钩子：类型 + 钩住的问题",
        "- 卷末快照：主角实力｜资源或势力净增｜当前最高层级敌人｜已埋未收的伏笔",
        "",
        "只输出这一卷的 Markdown，不要解释，不要代码围栏，不要重复前几卷。",
    ])
    user = "\n".join([
        _volume_material(root, project, next_no),
        "",
        f"全书计划 {target} 章" if target else "",
        f"请只输出第 {next_no} 卷的规划。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _append_volume(root: str | os.PathLike, block: str, next_no: int) -> list[dict[str, Any]]:
    with project_lock(root):
        project = _project(root)
        outline = str(project.get("outlineText") or "").rstrip()
        project["outlineText"] = (outline + "\n\n" + block.strip() + "\n").strip()
        project["updatedAt"] = _now()
        save_project(root, project)
    return refresh_volumes(root)


def rolling_status(root: str | os.PathLike) -> dict[str, Any]:
    project = _project(root)
    written = written_through(root)
    volumes = load_volumes(root)
    last_to = max((_num(v.get("to")) for v in volumes), default=0)
    memory = load_memory_rows(root)
    return {
        "writtenThrough": written,
        "nextChapter": written + 1,
        "compassText": _text(project.get("compassText")),
        "compassAt": str(project.get("compassAt") or ""),
        "targetChapters": _num(project.get("targetChapters")),
        "volumes": volumes,
        "plannedThrough": last_to,
        "needsVolume": bool(volumes) and written + 1 > last_to,
        "plannedChapters": max(0, last_to - written),
        "recentSummaries": [
            {"number": n, "summary": _text((memory.get("byChapter") or {}).get(n, {}).get("summary"))[:120]}
            for n in sorted((memory.get("byChapter") or {}))[-3:]
        ],
    }


def rolling_plan(
    root: str | os.PathLike,
    *,
    chapters: int = 5,
    model: str | None = None,
    force: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """滚动规划一次：必要时补下一卷，然后补下一批逐章细纲。"""
    project = _project(root)
    if not str(project.get("outlineText") or "").strip():
        raise ValueError("还没有大纲：先在「开书」页生成大纲+世界观，再滚动规划")
    written = written_through(root)
    start = written + 1
    try:
        target = int(project.get("targetChapters") or 0)
    except (TypeError, ValueError):
        target = 0
    if target and start > target:
        raise ValueError(f"已经写到第 {written} 章，超出全书计划 {target} 章；先改目标章数再规划")

    count = max(1, min(20, int(chapters or 5)))
    end = start + count - 1
    if target:
        end = min(end, target)

    volumes = load_volumes(root)
    last_to = max((_num(v.get("to")) for v in volumes), default=0)
    volume_result: dict[str, Any] | None = None
    if volumes and start > last_to:
        if on_stage:
            on_stage(f"补第 {len(volumes) + 1} 卷")
        result = chat(
            _volume_messages(root, project, len(volumes) + 1),
            model=model, temperature=0.6, max_tokens=6000, timeout=600,
            reasoning=reasoning_for("blueprint"), on_delta=on_delta,
        )
        block = strip_fence(str(result.get("text") or "")).strip()
        if len(block) < 120 or not _VOL_HEAD.search(block):
            raise LLMError(f"模型没有按卷头格式返回新卷，未保存。原文片段：{block[:200]}")
        span = _VOL_SPAN.search(block)
        if not span or not (int(span.group(1)) <= start <= int(span.group(2))):
            raise LLMError(
                f"新卷的章号区间没有盖住第 {start} 章，未保存；请重试或手动改大纲。"
                f"原文片段：{block[:200]}"
            )
        # 模型写进正文的章号可能越界，兜底只留 Markdown 本身，卷索引按卷头重新解析。
        volumes = _append_volume(root, block, len(volumes) + 1)
        volume_result = {
            "volume": len(volumes),
            "text": block,
            "model": str(result.get("model") or ""),
        }
        # 新卷的章号区间可能没盖住 start，细纲照写；卷索引刷不出来时前端会提示改卷头。
    elif on_stage:
        on_stage("沿用现有卷规划")

    if on_stage:
        on_stage(f"补第 {start}–{end} 章细纲")
    outlines = generate_outlines(
        root, frm=start, to=end, model=model, force=force,
        on_delta=on_delta if volume_result is None else None,
    )

    return {
        "ok": True,
        "from": start,
        "to": end,
        "volumeAdded": volume_result,
        "volumes": volumes,
        "outlines": outlines.get("outlines") or [],
        "spine": outlines.get("spine") or "",
        "reused": bool(outlines.get("reused")),
        "model": str(outlines.get("model") or (volume_result or {}).get("model") or ""),
        "compassUsed": bool(_text(project.get("compassText"))),
        "at": _now(),
    }
