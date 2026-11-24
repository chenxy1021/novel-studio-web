"""虐文骨架：把「最 X → 最非 X」的文案变成可执行的人物反转表 + 分章骨架。

只生成骨架，不写正文；每次生成追加一行到 ledger/nuewen.jsonl，读的时候取最新一条。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..llm import chat, strip_fence
from ..store import (
    append_jsonl,
    load_bible,
    load_project,
    project_lock,
    project_path,
    read_jsonl,
    save_project,
)
from .platforms import platform_brief

NUWEN_FILE = "ledger/nuewen.jsonl"

REVERSALS = """
1. 最想活的死，最想死的活下来。
2. 最乐观的死得最惨，最强的死得最屈辱。
3. 最骄傲的跪地求饶，最光明的沉沦黑暗。
4. 最自尊的颜面尽失，最自私的为大义牺牲。
5. 最真心的被谎言埋葬，最善算计的终局反噬。
6. 最被呵护的当场凋零，最求团圆的孤独长生。
7. 最重亲人的成魔弑亲。
8. 最强大者看着朋友一个个死去，无能为力。
9. 最小的那个站在一堆墓碑前说：「现在我比你们都大了。」
10. 最后留一个主角半死不活，作为这一切的见证者。
""".strip()

SYSTEM = """你是擅长写虐文的作者。你要做的不是随机发刀，而是精准反转每个角色最珍视的东西。
虐点 = 角色最想要、最怕失去、最骄傲、最依赖的东西，被命运和他自己的选择，反转成它的反面。
先立「最」，再让反转由人物选择推动，最后让反转互相咬合。只输出结构化文本，不写正文。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    return project


def _characters(root: str | os.PathLike) -> str:
    bible = load_bible(root)
    rows = []
    for c in (bible.get("characters") or [])[:8]:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            f"- {name}：身份「{c.get('rolePosition') or c.get('role') or '—'}」；"
            f"想要「{c.get('want') or '—'}」；怕「{c.get('fear') or '—'}」；"
            f"说话「{c.get('voice') or '—'}」"
        )
    return "\n".join(rows) or "（bible 里还没有人物卡。请根据作品信息创建 4–6 个角色，并写清他们各自「最」什么。）"


def build_messages(root: str | os.PathLike, instruction: str = "") -> list[dict[str, str]]:
    project = _project(root)
    current = int(project.get("currentChapter") or 0)
    start = max(1, current + 1)
    end = start + 9
    user = f"""【作品】{project.get('title') or ''}｜{project.get('genre') or ''}｜{project.get('tone') or ''}
【一句话】{project.get('logline') or ''}
【主题】{project.get('theme') or project.get('spine') or ''}
【简介】{project.get('synopsis') or ''}

【平台打法（骨架要适配）】
{platform_brief(project.get('platform'))}

【已有角色】
{_characters(root)}

【必须使用的反转（按人物分配；可以一人承担多条，不要平均分）】
{REVERSALS}

【这次只做两件事】
1. 人物反转表：| 角色 | 他最「最」什么（具体物件/习惯/话） | 反转成什么 | 谁/什么推动 | 第几章落地 | 对别人的连锁影响 |
2. 第 {start}–{end} 章的分章骨架：每章写清「本章目标 / 主角的选择 / 付出的代价 / 章末钩子」，并标明本章执行的是哪条反转。

【硬要求】
- 每个「最」必须具体到物件、习惯或一句常说的话；没有细节的不算。
- 每个反转必须有因果链：性格 → 压力下的选择 → 代价落地。禁止天灾、巧合、误会降智硬转。
- 反转要咬合：一个人的结局必须成为另一个人的压力源。
- 十条反转不要平均分给每个角色；选 3–5 条做主线，其余给配角和支线。没有用到的要说明留到后面哪一段。
- 只输出表格和分章骨架，不要写正文，不要解释方法。
{('【作者补充】' + instruction.strip()) if instruction.strip() else ''}
"""
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def read_mode(root: str | os.PathLike) -> bool:
    project = load_project(root) or {}
    return bool(project.get("nuewen"))


def set_mode(root: str | os.PathLike, enabled: bool) -> dict[str, Any]:
    with project_lock(root):
        project = _project(root)
        project["nuewen"] = bool(enabled)
        project["updatedAt"] = _now()
        save_project(root, project)
    return {"enabled": bool(enabled)}


def read_plan(root: str | os.PathLike) -> dict[str, Any]:
    rows = read_jsonl(project_path(root, NUWEN_FILE))
    latest: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict) or row.get("__corrupt"):
            continue
        if row.get("kind") != "plan" or not str(row.get("text") or "").strip():
            continue
        latest = row
    enabled = read_mode(root)
    if not latest:
        return {"text": "", "at": "", "model": "", "enabled": enabled}
    return {
        "text": str(latest.get("text") or ""),
        "at": str(latest.get("at") or ""),
        "model": str(latest.get("model") or ""),
        "enabled": enabled,
    }


def generate_plan(
    root: str | os.PathLike,
    *,
    instruction: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    messages = build_messages(root, instruction)
    result = chat(
        messages,
        model=model,
        temperature=0.7,
        max_tokens=9000,
        timeout=300,
        reasoning="low",
    )
    text = strip_fence(result["text"]).strip()
    if len(text) < 200:
        raise ValueError("模型返回的骨架过短，没有落账")
    row = {
        "kind": "plan",
        "at": _now(),
        "model": str(result.get("model") or ""),
        "instruction": instruction.strip(),
        "text": text,
    }
    append_jsonl(project_path(root, NUWEN_FILE), row)
    return {"text": text, "at": row["at"], "model": row["model"]}
