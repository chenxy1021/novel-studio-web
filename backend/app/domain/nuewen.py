"""虐文骨架：把「最 X → 最非 X」的文案变成可执行的人物反转表 + 分章骨架。

只生成骨架，不写正文；每次生成追加一行到 ledger/nuewen.jsonl，读的时候取最新一条。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..llm import chat, strip_fence
from ..llm.routing import reasoning_for
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
这些句子不是十个桥段，是十种「价值被反转」的示范。不要按句子分配任务，也不要字面执行。
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

#: 这十句真正要传达的感觉。正文、改写这类「已经在写具体章节」的提示词只带这一段，
#: 不带十句清单——清单会诱导模型逐条安排惨剧。
FEELING = """它们真正共同的地方只有三件事：
- 一个人把全部自我押在某样东西上——那就是他的「最」；
- 反转不是天降灾难，是这个「最」在压力下自己走向反面；
- 落地之后，世界照常运转，但他再也回不到原来的位置。

体会这个逻辑，不要抄这些句子的表面结局，也不要按句子分配任务。"""

REVERSALS = REVERSALS + "\n\n" + FEELING

#: 正文与改写共用的执行纪律。核心是让「虐」长在人物身上，而不是长在清单上。
CRAFT = """
- 先让读者爱上那个「最」：同一个物件/习惯/一句话，先写出它对他的意义，再让它变味。不要让角色自己说「我最在乎……」，也不要在旁白里标注「这是他的最」。
- 反转的推动力必须长在人物身上：他的性格、信念、软肋。按他当时的认知，这个选择要合理，甚至是最合理的那条；代价是事后才显形的。读者看得见，他看不见。
- 读者要能看见「他本可以不这样」，但仍然理解他为什么只能这样。
- 写失去，不写惨状；写他还在硬撑的那部分，比写他崩溃更疼。
- 不预设结局形状：可以死、可以活、可以赢，只要那是因果链自己走到的。不要为了「虐」硬写死光、剩一个或翻盘。
- 收在动作、停顿、重复的细节或一句反常的话上；不写「她终于明白」「原来一切都……」式总结和抒情。
""".strip()

#: 作者反馈「写得太傻」的典型，命中就重写。放在提示词里当硬性反面清单。
DUMB = """
- 绝症、车祸、失忆、偷听半句、故意不说人话推动误会。
- 为了让主角惨，让配角集体降智、送死、无理由发疯。
- 连续两章同一种虐法（误会 / 生病 / 下跪 / 挡刀 / 淋雨）。
- 死亡当 KPI：一章死一个，只为制造情绪。
- 角色站在原地自我感动、长篇回忆杀、作者跳出来总结主题。
""".strip()

SYSTEM = """你是擅长写虐文的作者。你要做的不是随机发刀，而是精准反转每个角色最珍视的东西。
虐点 = 角色最想要、最怕失去、最骄傲、最依赖的东西，被命运和他自己的选择，反转成它的反面。
先立「最」，再让反转由人物选择推动，最后让反转互相咬合。只输出结构化文本，不写正文。
注意：原型池是灵感来源，不是任务清单；不要为了套公式让角色降智、轮流倒霉或集体送死。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    return project


def _samples(c: dict[str, Any]) -> str:
    raw = c.get("voiceSamples")
    lines = [str(x).strip() for x in raw if str(x).strip()][:2] if isinstance(raw, list) else []
    return ("；口吻样例：「" + "」「".join(lines) + "」") if lines else ""


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
            + (_samples(c))
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

【感受这些句子，不要按句子分配任务】
{REVERSALS}

【这次只做两件事】
1. 人物反转表：| 角色 | 他最「最」什么（具体物件/习惯/话） | 反转成什么 | 他当时为什么认为这是对的 | 谁/什么推动 | 第几章落地 | 对别人的连锁影响 |
2. 第 {start}–{end} 章的分章骨架：每章写清「本章目标 / 主角的选择 / 付出的代价 / 章末钩子」，以及这一章让谁的「最」发生了什么变化。

【硬要求】
- 每个「最」必须具体到物件、习惯或一句常说的话；没有细节的不算。
- 反转必须长在人物身上：性格 → 压力下的选择 → 代价落地。禁止天灾、巧合、误会降智硬转。
- 反转表里多写一列「他当时为什么认为这是对的」：选择必须在当时的认知里合理，代价是事后才显形的。
- 反转要咬合：一个人的处境变化必须成为另一个人的压力源，不要各惨各的。
- 不要为了对应某条原型硬造情节；原型只用来校准感觉。没有用到的句子不用交代。
- 不要预设结局形状：可以死、可以活、可以赢，只要那是因果链自己走到的；不要用死亡数量衡量虐度。
- 只输出表格和分章骨架，不要写正文，不要解释方法。

【写成这样就重写】
{DUMB}
- 为了套「最 X → 最非 X」，让角色做明显更笨的选择。
- 角色自己宣言「我最在乎的就是……」；作者跳出来总结「这就是命」。
- 结局按固定模板收：要么死光，要么剩一个见证者，要么强行翻盘。
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
        reasoning=reasoning_for("rewrite"),
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
