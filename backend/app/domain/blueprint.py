"""开书第二步：由「故事梗概」一次生成「大纲 + 世界观」。

旧插件的流程是 outline-gen 和 world-gen 两个入口，但作者的实际顺序是：
选题（梗概）→ 立结构。结构里既要有可执行的大纲，也要有能支撑大纲的世界；
分两次点只会让世界观脱离大纲、各写各的。所以这里合成一次调用：

- 素材只给「梗概 + 体量 + 平台（+ 虐文公式）」，不读 bible 里的人物/规则
  （那些是下一步「设定」的产物，提前喂进来会和后文打架）；
- 输出一份 Markdown，前半是「全书层 + 卷层」大纲，后半是叙事性世界观；
- 落盘时拆开：project.outlineText / project.worldText，另存 blueprintText；
- 卷索引按「### 第N卷 卷名（第a-b章）」解析，刷新到 ledger/volumes.json。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from ..store import load_project, project_lock, save_project, written_through
from .memory import refresh_volumes
from .nuewen import REVERSALS
from .platforms import platform_brief, platform_rules

_PART2 = re.compile(r"^\s*#{1,4}\s*(?:第[二2]\s*部分|二[、.．])\s*[:：]?\s*(?:世界观|世界设定|世界)\s*$", re.M)
_PART2_FALLBACK = re.compile(r"^\s*#{1,4}\s*(?:世界观|世界设定)\s*$", re.M)
_CHAPTER_NUM = re.compile(r"第\s*(\d{1,5})\s*章")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project(root: str | os.PathLike) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    return project


def _nuewen_block() -> str:
    return f"""【虐文的感觉（落进大纲和世界观，不是贴标签，也不是套模板）】
{REVERSALS}
- 不要从这十句里挑几条分配成任务；先找到每个核心角色把全部自我押在哪件具体的东西上（物件、习惯、一句常说的话），大纲里写清它在哪一章被回收、怎么变味。
- 反转由他的选择推动：性格 → 压力下的选择 → 代价落地。选择在当时的认知里必须合理，代价是事后才显形的。
- 反转要咬合：一个人的处境变化必须成为另一个人的压力源，不要各惨各的。
- 不预设结局形状：可以死、可以活、可以赢，只要那是因果链自己走到的；不要为了「不圆满」硬写死光、剩一个见证者或强行翻盘。
- 不要用死亡数量衡量虐度：卷末的不可逆变化优先写关系、身份、信念的破裂。
"""


def build_messages(project: dict[str, Any]) -> list[dict[str, str]]:
    title = str(project.get("title") or "未命名")
    genre = str(project.get("genre") or "未定")
    platform = str(project.get("platform") or "通用")
    synopsis = str(project.get("synopsis") or "").strip()
    logline = str(project.get("logline") or "").strip()
    tone = str(project.get("tone") or "").strip()
    if not synopsis:
        raise ValueError("还没有故事梗概：先回到新书选题，选一个带梗概的选题再开书")

    try:
        chapters = int(project.get("targetChapters") or 100)
    except (TypeError, ValueError):
        chapters = 100
    chapters = max(1, min(5000, chapters))
    try:
        wpc = int(project.get("wordsPerChapter") or 0)
    except (TypeError, ValueError):
        wpc = 0
    rules = platform_rules(platform)
    if not wpc:
        wpc = int(rules.get("wordsMin") or 0)
    total_wan = chapters * wpc / 10000

    material = "\n".join([
        f"书名：{title}",
        f"题材：{genre}",
        f"发布平台：{rules['name']}",
        f"规模：约 {chapters} 章" + (f"，每章约 {wpc} 字，全书约 {total_wan:.1f} 万字" if wpc else ""),
        f"一句话：{logline or '（无）'}",
        f"故事梗概：{synopsis}",
        f"作者指定的气质：{tone or '（未指定）'}",
    ])

    nuewen = bool(project.get("nuewen"))
    system = "\n".join([
        "你是中文网文的总编，负责把选题梗概落成一份可直接开写的蓝图。你不写正文，只输出 Markdown。",
        "蓝图分两部分：第一部分是全书大纲（全书层 + 卷层），第二部分是叙事性世界观。",
        "",
        "# 硬性要求",
        "1. 每个节拍必须是可观察的事件：谁对谁做了什么、谁失去或得到了什么。禁止「他意识到局势不妙」「气氛紧张」这类总结。",
        "2. 全书层必须回答：一句话故事核、主角的欲望/恐惧/致命缺陷、主线六节点（起点 → 第一次转折 → 中点大转折 → 虚假胜利 → 最低谷 → 结局）、结局必须回答的问题、主题。",
        "3. 前 3 章固定三拍：第1章触发（主角被卷入）→ 第2章加码（代价具体到钱、亲人、资格）→ 第3章反制有结果但引出更大反噬。",
        "4. 分卷按内容，不按章节数平均切：每卷是一个完整的矛盾阶段（目标 → 升级 → 卷末不可逆变化），"
        "阶段结束在哪儿，卷就分到哪儿；短卷可以十几章，长卷可以几十章。"
        "先按故事的自然转折定卷，再把章号区间标出来，不要为了凑数硬分。",
        "5. 卷头格式一字不差：### 第N卷 卷名（第a-b章）；用阿拉伯数字、半角连字符，卷名不超过 8 字。"
        "所有卷首尾相接，正好覆盖第 1 章到第 "
        f"{chapters} 章；区间长短由内容决定，允许每卷不同。",
        "6. 大纲只写结构：不要输出人物卡、势力字段表、物品清单、规则清单；这些由下一步「设定」统一生成。",
        "7. 世界观写「世界是什么样、为什么是这样、人怎么在里面活」：世界基底、历史、地理、体系如何运作、势力恩怨、日常氛围、自洽检查。",
        "8. 世界观里不要在正文列表格式堆设定条目，但要把将来能拆成规则的东西讲清楚：什么能做、什么不能做；"
        "设定里有代价/反噬就写清，没有就写边界，不要为了「有深度」硬给异能加反噬。",
        "9. 全文控制在 5000 字以内，信息密度优先。不确定的地方写「待定：」并给推荐默认值。",
        "",
        "# 输出格式（严格，纯 Markdown，不要代码围栏）",
        "## 第一部分：全书大纲",
        "### 0. 素材研判",
        "- 能确定的核心（≤5 条）",
        "- 素材里的矛盾或空白，以及你打算怎么处理",
        "### 1. 全书层",
        "- 一句话故事核：谁 + 想要什么 + 被什么挡住 + 代价",
        "- 主角的欲望、恐惧、致命缺陷",
        "- 主线六节点：起点 → 第一次转折 → 中点大转折 → 虚假胜利 → 最低谷 → 结局",
        "- 结局必须回答的问题",
        "- 主题：一句话，必须能在高潮处被事件证明",
        "- 支线表：| 支线 | 发起卷 | 交汇章 | 收束章 | 给主线提供 |",
        "- 对手阶梯表：| 章段 | 对手层级 | 与主角的差距 | 主角若输要付的代价 |",
        "### 2. 卷层",
        "### 第1卷 卷名（第1-30章）",
        "- 任务与矛盾：……",
        "- 卷内节拍：3-5 拍，每拍写「谁做了什么 → 谁失去/得到什么」",
        "- 卷末钩子：类型（信息/危机/悬念/反差）+ 钩住的问题",
        "- 卷末快照：主角实力｜资源或势力净增｜当前最高层级敌人｜已埋未收的伏笔",
        "（按此格式继续第2卷、第3卷……直到第 "
        f"{chapters} 章）",
        "## 第二部分：世界观",
        "### 1. 世界基底",
        "### 2. 历史与时间线",
        "### 3. 地理与空间",
        "### 4. 体系如何运作",
        "### 5. 势力与恩怨",
        "### 6. 日常与氛围",
        "### 7. 自洽检查",
        "",
        "# 自检",
        "- [ ] 卷头严格是「### 第N卷 卷名（第a-b章）」，区间连续覆盖 1-"
        f"{chapters} 章，无重叠、无断档",
        "- [ ] 每个节拍都有可观察的得失，没有「他意识到 / 气氛紧张」",
        "- [ ] 世界观能支撑大纲里的关键事件（代价、权限、信息差都说得通）",
        "- [ ] 没有把人物卡/势力表/物品清单塞进大纲或世界观正文",
    ])
    if nuewen:
        system += "\n\n" + _nuewen_block()

    user = "\n".join([
        "以下是这本书的全部素材：",
        "",
        "<素材>",
        material,
        "</素材>",
        "",
        f"请一次输出「第一部分：全书大纲」和「第二部分：世界观」。全书共 {chapters} 章"
        + (f"，每章约 {wpc} 字" if wpc else "")
        + f"，卷层必须一路铺到第 {chapters} 章。平台：{rules['name']}。",
        platform_brief(platform),
        "只输出 Markdown，不要解释，不要代码围栏。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _split_parts(text: str) -> tuple[str, str]:
    """把模型输出拆成（大纲, 世界观）；模型偶尔只写一个总标题，尽量宽容。"""
    s = strip_fence(text).strip()
    m = _PART2.search(s) or _PART2_FALLBACK.search(s)
    if m:
        return s[:m.start()].strip(), s[m.end():].strip()
    # 没有第二部分：尝试找「## 世界观」之前用「全书大纲」开头
    return s, ""


def _clean_outline(outline: str) -> str:
    # 去掉「第一部分」这层壳，只留下面的大纲小节；保留卷头给 volumes 解析。
    s = re.sub(r"^\s*#{1,4}\s*第[一1]\s*部分\s*[:：]?\s*(?:全书)?大纲\s*$", "", outline, count=1, flags=re.M)
    return s.strip()


def generate_blueprint(
    root: str | os.PathLike,
    *,
    nuewen: bool | None = None,
    model: str | None = None,
    on_delta: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    project = _project(root)
    if nuewen is not None and bool(project.get("nuewen")) != bool(nuewen):
        project["nuewen"] = bool(nuewen)
    messages = build_messages(project)
    if on_stage:
        on_stage("生成大纲")
    result = chat(
        messages, model=model, temperature=0.7, max_tokens=16000, timeout=600, reasoning=reasoning_for("blueprint"),
        on_delta=on_delta,
    )
    if on_stage:
        on_stage("拆分世界观")
    text = strip_fence(str(result.get("text") or "")).strip()
    if len(text) < 120:
        raise LLMError(f"模型返回的蓝图过短，未保存。原文片段：{text[:200]}")

    outline, world = _split_parts(text)
    outline = _clean_outline(outline)
    if not re.search(r"全书层|一句话故事核|素材研判|卷层", outline):
        raise LLMError(f"模型返回的内容不像大纲，未保存。原文片段：{outline[:200]}")
    if not world:
        # 没拆出来时退一步：整份存进大纲，世界观下一步让作者单独重跑
        world = ""
    elif not re.search(r"世界基底|地理|势力|自洽|体系", world):
        # 世界部分没有可辨认的小节，也保留原文，至少不丢内容
        world = world.strip()

    try:
        chapters = int(project.get("targetChapters") or 0)
    except (TypeError, ValueError):
        chapters = 0
    nums = [int(n) for n in _CHAPTER_NUM.findall(outline)]
    max_seen = max(nums) if nums else 0
    warning = ""
    if chapters >= 20 and max_seen and max_seen < chapters * 0.6:
        warning = (
            f"大纲只铺到第 {max_seen} 章，离你定的 {chapters} 章差得远（后半本没有大纲）。"
            "点「换一版」重新生成，或手动补卷。"
        )
    if not world:
        warning = (warning + " " if warning else "") + "模型没有输出「第二部分：世界观」，建议点「换一版」重生成。"

    at = _now()
    with project_lock(root):
        current = _project(root)
        current["outlineText"] = outline
        current["worldText"] = world
        current["blueprintText"] = text
        if nuewen is not None:
            current["nuewen"] = bool(nuewen)
        current["outlineAt"] = at
        current["worldAt"] = at if world else str(current.get("worldAt") or "")
        current["gate"] = {
            "phase": "planning",
            "chapter": max(1, written_through(root) + 1),
            "reason": "大纲和世界观已就位，下一步生成人物 / 规则 / 物品 / 地点等设定",
            "at": at,
        }
        current["updatedAt"] = at
        save_project(root, current)

    volumes = refresh_volumes(root)
    return {
        "outlineText": outline,
        "worldText": world,
        "volumes": volumes,
        "targetChapters": chapters,
        "maxChapterSeen": max_seen,
        "warning": warning,
        "model": str(result.get("model") or ""),
        "at": at,
    }
