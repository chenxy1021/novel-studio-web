"""AI 选题：按作者给的方向/题材/卖点，出几个可直接开书的候选。

对齐旧插件的「想法 → 选题」两步：
- 章数和每章字数是硬输入，决定选题体量；
- 题材、卖点可以留空，留空就由模型补；
- 书名和简介都从选题里长出来，点「出选题」后由模型生成；
- 勾了虐文时，按「最 X → 最非 X」的公式出选题，而不是普通悲剧；
- 点「换一批」时把上一批带回去，避免每轮都收敛到同一套骨架。

只产候选，不写项目文件；建书仍走 create.create_book。
"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..llm.routing import reasoning_for
from .nuewen import REVERSALS
from .platforms import platform_brief, platform_rules

# 用户没给题材时，随机分配不同赛道，防止模型每次都挑同一撮。
GENRE_LANES = [
    "都市异能 / 都市现实", "玄幻仙侠 / 修真", "科幻 / 末世 / 星际", "历史 / 权谋 / 争霸",
    "武侠 / 江湖", "军事 / 谍战", "赛博朋克 / 近未来",
    "职场 / 商战", "体育 / 竞技", "校园 / 青春",
    "医疗 / 法医 / 刑侦", "克苏鲁 / 无限流 / 规则怪谈",
    "悬疑推理 / 民俗怪谈 / 灵异",
]
_MYSTERY_LANE = re.compile(r"悬疑|推理|刑侦|民俗|怪谈|克苏鲁|灵异|无限流|规则|鬼|恐怖")

_SYSTEM = """你是一位资深网文选题策划编辑。你的唯一价值是产出「彼此一眼就不同、都能直接开写」的选题。
只输出 JSON，不要任何解释。

【差异化铁律：候选之间必须在下面这些格子上互不相同】
1. 赛道（genre 大类）——大类不许相同（作者指定了题材时以题材约束为准）。
2. 时代/世界——不同年代或不同世界类型。
3. 主角格局与身份——社会位置要拉开，别都挤在同一种「边缘小人物」。
4. 核心冲突层级——个人恩怨 / 组织博弈 / 阶层或体制对抗 / 世界法则之争，各选不同层级。
5. 金手指类型——系统 / 血脉 / 知识降维 / 规则漏洞 / 身份马甲 / 时代红利，各选不同来源。
6. 爽点来源——打脸复仇 / 经营收米 / 解谜破局 / 攻城略地 / 权力逆袭 / 收集养成 / 科技碾压，各选不同爽法。
7. 叙事切口——重生回档 / 藏身份 / 夺权开局 / 被卷入大事件 / 反派出场，各选不同切入点。

【反套路配方：最多用一次】
「诗意边缘职业 + 诡异氛围 + 寄生在某营生/物件上」（守夜人、点灯人、收尸人、卖记忆/卖情绪的小贩……）可以用，但最多一题；
「交易/贩卖记忆/寿命/情绪」当金手指，也最多一题。不许每批都靠同一套。

【单题最低要求】
- synopsis 是核心交付物，180–260 字：谁、想要什么、被什么挡、爽在哪、往哪走；讲清到读者能立刻脑补，不剧透结局，不堆形容词。
- oneLine 一句话卖点，≤20 字，要能勾住人。
- title 书名 2–10 字；另给 2 个 titleOptions 备选。
- hitRate 给 high / mid / low，hitReason 一句理由（≤40 字）。
- differentiation 写「同类通常怎么做 → 我改成什么」（≤60 字）；risk 写最易写崩在哪（≤40 字）。

【JSON 写法（必须遵守）】
- 严格 JSON：字段名和字符串都用英文双引号；字符串里不要再出现英文双引号。
- 正文里需要引号时用中文「」或『』（例：「养液」），不要写成 "养液"。
- 不要尾逗号，不要注释，不要 Markdown 代码块。

【合规（一票否决）】
不写可操作的违法犯罪细节；不写未成年人性化内容；不复制他人作品原句。
"""

_NUWEN_SYSTEM = f"""你是资深虐文选题策划。你只产出「彼此一眼不同、都能直接开写」且真的虐的选题；
不产出普通悲剧，也不产出「先虐后爽、最后翻盘」的伪虐文。只输出 JSON，不要解释。

【核心公式：先立「最」，再把它反转成「最非」】
{REVERSALS}

【什么叫真的虐】
- 虐点不是惨，是角色最想要、最骄傲、最依赖、最怕失去的东西，被因果链反转成它的反面。
- 反转必须由人物自己的选择推动：性格 → 压力下的选择 → 代价落地。选择在当时的认知里要合理，代价是事后才显形的。
- 禁止天灾、巧合、绝症、车祸、失忆、偷听半句、误会降智、反派无理由发疯。
- 反转要咬合：一个人的处境变化必须成为另一个人的压力源，不要各惨各的。
- 不预设结局形状：可以死、可以活、可以赢，只要那是因果链自己走到的。不要为了「虐」硬写死光、剩一个见证者或强行翻盘。
- 不要用死亡数量衡量虐度；优先写关系、身份、信念的破裂。

【差异化铁律】候选之间在赛道、时代/世界、主角身份、核心冲突层级、叙事切口上互不相同；
任意一列像同一个模子换皮，就换掉重写。作者指定了题材时，题材不换，改在其余列和反转类型上拉开。
【单题最低要求】
- synopsis 180–260 字：必须让读者看见至少 2 个具体反转（谁的最什么 → 被怎么反转），
  不是概括「命运坎坷」；写清因果，不堆形容词，不剧透最后一场。
- oneLine ≤20 字；title 2–10 字，贴虐点，不要起爽文/甜文名；另给 2 个 titleOptions。
- hitRate 给 high / mid / low，hitReason ≤40 字；differentiation ≤60 字；risk ≤40 字。
- 额外输出 nuewen 结构：
  most：主角最「最」的具体东西，必须具体到物件、习惯或一句常说的话；
  turns：2–4 条具体反转，每条写清「他做了什么选择 → 失去了什么」；
  aftertaste：反转落地后谁还在、世界怎么继续、余味从哪来（≤60 字；不规定必须有人活着或死去）；
  chain：反转之间怎么互相咬合（≤80 字）。

【JSON 写法（必须遵守）】
- 严格 JSON：字段名和字符串都用英文双引号；字符串里不要再出现英文双引号。
- 正文里需要引号时用中文「」或『』（例：「养液」），不要写成 "养液"。
- 不要尾逗号，不要注释，不要 Markdown 代码块。

【合规（一票否决）】
不写可操作的违法犯罪细节；不写未成年人性化内容；不复制他人作品原句。
"""


def _normalize_count(value: Any, default: int = 3) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(5, n))


def _escape_inner_quotes(s: str) -> str:
    """把字符串值里没转义的英文双引号补上反斜杠。

    模型常写 "synopsis":"她凝成"养液"，喝一口……"——两侧引号在 JSON 里是
    结束/开始字符串，解析直接崩。这里按「引号后面跟 , } ] : 才算结束」判断，
    其余引号一律转义。只用于严格解析失败后的第二次尝试。
    """
    out: list[str] = []
    in_str = escaped = False
    for i, ch in enumerate(s):
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_str:
            out.append(ch)
            escaped = True
            continue
        if ch != '"':
            out.append(ch)
            continue
        if not in_str:
            in_str = True
            out.append(ch)
            continue
        nxt = i + 1
        while nxt < len(s) and s[nxt] in " \t\r\n":
            nxt += 1
        if nxt >= len(s) or s[nxt] in ",}]:":
            in_str = False
            out.append(ch)
        else:
            out.append('\\"')
    return "".join(out)


def _loads_loose(raw: str) -> Any:
    """严格 JSON 失败后依次尝试：去尾逗号、转义字符串内引号、两者一起。"""
    stripped = re.sub(r",\s*([}\]])", r"\1", raw)
    for attempt in (raw, stripped, _escape_inner_quotes(raw), _escape_inner_quotes(stripped)):
        try:
            return json.loads(attempt)
        except (TypeError, ValueError):
            continue
    return None


def _extract_json(text: str) -> Any:
    """从模型输出里找出 JSON：先整体解析，再退到数组片段和逐个对象抢救。"""
    s = strip_fence(text or "").strip()
    if not s:
        return None
    parsed = _loads_loose(s)
    if parsed is not None:
        return parsed

    start, end = s.find("["), s.rfind("]")
    if start >= 0 and end > start:
        parsed = _loads_loose(s[start:end + 1])
        if parsed is not None:
            return parsed

    # 截断时前面的完整对象仍然可用：按大括号配对扫，跳过字符串里的括号。
    # 先补内层引号，否则引号提前「结束」会让括号配对错位。
    scan = _escape_inner_quotes(s)
    objects: list[Any] = []
    depth = 0
    begin = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(scan):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                begin = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and begin >= 0:
                    piece = _loads_loose(scan[begin:i + 1])
                    if piece is not None:
                        objects.append(piece)
                    begin = -1
    return objects or None


def _list_from_payload(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        # 模型有时用 {"0": {...}, "1": {...}} 或单个对象
        values = [v for v in payload.values() if isinstance(v, (dict, str))]
        if values and all(isinstance(v, dict) for v in values):
            return values
        return [payload]
    return []


def _text(value: Any, limit: int = 0) -> str:
    s = str(value or "").strip()
    if limit and len(s) > limit:
        s = s[:limit].strip()
    return s


def _title_options(raw: Any, title: str) -> list[str]:
    out: list[str] = []
    for x in raw if isinstance(raw, list) else []:
        item = _text(x, 40)
        if item and item != title and item not in out:
            out.append(item)
    return out[:3]


def _hit_rate(raw: Any) -> str:
    s = _text(raw).lower()
    if s in {"high", "mid", "low"}:
        return s
    return {"高": "high", "中": "mid", "低": "low"}.get(s, "")


def _nuewen_block(raw: dict[str, Any]) -> dict[str, Any] | None:
    """虐文结构：模型有时放 nuewen 对象里，有时平铺，两种都收。"""
    obj = raw.get("nuewen")
    if not isinstance(obj, dict):
        obj = {
            "most": raw.get("most"),
            "turns": raw.get("turns") or raw.get("reversals"),
            "aftertaste": raw.get("aftertaste") or raw.get("witness"),
            "chain": raw.get("chain"),
        }
    most = _text(obj.get("most"), 120)
    raw_turns = obj.get("turns") or obj.get("reversals") or []
    if isinstance(raw_turns, str):
        raw_turns = re.split(r"[\n；;]+", raw_turns)
    turns = [_text(x, 160) for x in raw_turns if _text(x)][:4] if isinstance(raw_turns, list) else []
    # 旧缓存里叫 witness；语义已改成「余味」，不再要求必须有人活下来。
    aftertaste = _text(obj.get("aftertaste") or obj.get("witness"), 160)
    chain = _text(obj.get("chain"), 160)
    if not any((most, turns, aftertaste, chain)):
        return None
    return {"most": most, "turns": turns, "aftertaste": aftertaste, "chain": chain}


def _clean_concept(
    raw: Any,
    index: int,
    platform: str,
    fallback_genre: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _text(raw.get("title") or raw.get("name"), 60)
    one_line = _text(raw.get("oneLine") or raw.get("logline"), 80)
    synopsis = _text(raw.get("synopsis"))
    if not title or not (synopsis or one_line):
        return None
    return {
        "id": _text(raw.get("id"), 80) or f"concept-{index + 1}",
        "title": title,
        "titleOptions": _title_options(raw.get("titleOptions"), title),
        "genre": _text(raw.get("genre"), 40) or fallback_genre,
        "oneLine": one_line,
        "synopsis": synopsis,
        "hitRate": _hit_rate(raw.get("hitRate")),
        "hitReason": _text(raw.get("hitReason"), 80),
        "differentiation": _text(raw.get("differentiation"), 120),
        "risk": _text(raw.get("risk"), 80),
        "platform": platform_rules(platform)["name"],
        "nuewen": _nuewen_block(raw),
    }


def _prompt(
    *,
    direction: str,
    genre: str,
    logline: str,
    platform: str,
    target_chapters: int,
    words_per_chapter: int,
    count: int,
    avoid: list[str],
    nuewen: bool = False,
) -> list[dict[str, str]]:
    rules = platform_rules(platform)
    total_words = target_chapters * words_per_chapter
    short = bool(rules.get("short")) or target_chapters <= 50
    # 没给方向/题材时，随机挑不同赛道；用户给了就按用户的来。
    follow_user = bool(direction or genre)
    lanes: list[str] = []
    if not follow_user:
        pool = [lane for lane in GENRE_LANES if _MYSTERY_LANE.search(direction + genre) or not _MYSTERY_LANE.search(lane)]
        lanes = random.sample(pool, min(count, len(pool)))

    user_lines = [
        f"出 {count} 个{'短篇' if short else '长篇'}{'虐文' if nuewen else ''}选题候选（{'一稿完结' if short else '可连载'}，不是一句点子）。",
        f"作者方向：{direction or '不限'}",
        f"题材类型：{genre or '不限'}",
        "书名：由你根据选题自己起，2–10 字；书名要贴着这个故事，不要先起名再凑故事。",
        f"指定卖点：{logline or '无'}",
        f"目标规模：约 {target_chapters} 章 × 每章约 {words_per_chapter} 字（合计约 {total_words / 10000:.1f} 万字）。",
        f"发布平台：{rules['name']}",
        platform_brief(platform),
        f"必须给满 {count} 个完整候选，少一个都算不合格；每个候选的 synopsis 都要写满。",
    ]
    if nuewen:
        user_lines.append(
            "【本批是虐文模式】写「他的最被自己的选择反转」，不要写成先虐后爽。"
            "每个 synopsis 至少要看见两个具体反转，反转之间要互相咬合；"
            "不要预设结局形状，更不要为了虐强行写死、剩一个见证者或翻盘。"
        )
    if lanes:
        user_lines.append(
            "【本批赛道】三个候选按下面分配，genre 写成「大类·细分」：\n"
            + "\n".join(f"{i + 1}）{lane}" for i, lane in enumerate(lanes))
        )
    if follow_user:
        user_lines.append(
            "【题材约束】作者已经指定方向/题材：三个候选都要落在这个题材里，不许为了差异化跑到作者没要的题材；"
            "改为在主角身份、核心冲突层级、叙事切口"
            + ("、反转类型" if nuewen else "、爽点来源")
            + "上拉开。"
        )
    if target_chapters >= 200:
        user_lines.append(f"这是长篇连载：核心矛盾要撑得住 {target_chapters} 章的体量，不能二三十章就写完。")
    if avoid:
        user_lines.append(
            "上一批已经出过下面这些，这一批一个都不许重复（换说法、换地名、换职业但骨架一样也算重复）：\n"
            + "\n".join(f"- {x}" for x in avoid[-20:])
        )
    schema = (
        '"title":"书名(2-10字)","titleOptions":["备选1","备选2"],"genre":"大类·细分",'
        '"oneLine":"一句话卖点(≤20字)","synopsis":"故事梗概(180-260字)",'
        '"hitRate":"high|mid|low","hitReason":"一句理由(≤40字)",'
        '"differentiation":"同类通常怎么做→我改成什么(≤60字)","risk":"最易写崩在哪(≤40字)"'
    )
    if nuewen:
        schema += (
            ',"nuewen":{"most":"主角最「最」的具体东西","turns":["选择→失去","选择→失去"],'
            '"aftertaste":"反转落地后的余味","chain":"反转怎么互相咬合"}'
        )
    user_lines += [
        "【输出】严格只输出一个 JSON 数组，不要任何解释。每个元素形如：",
        "{" + schema + "}",
    ]
    if nuewen:
        user_lines.append(
            "输出前自检：每题至少两个具体反转／反转由人物选择推动／结局由因果链走到而不是套模板／"
            "nuewen.most 具体到物件或一句话／书名贴虐点／JSON 可解析。"
        )
    else:
        user_lines.append("输出前自检：候选之间各列无重复／synopsis 都在 180–260 字／书名 2–10 字／JSON 可解析。")
    return [
        {"role": "system", "content": _NUWEN_SYSTEM if nuewen else _SYSTEM},
        {"role": "user", "content": "\n".join(line for line in user_lines if line)},
    ]


def generate_concepts(
    *,
    direction: str = "",
    genre: str = "",
    logline: str = "",
    platform: str = "generic",
    target_chapters: int,
    words_per_chapter: int,
    count: int = 3,
    avoid: list[str] | None = None,
    nuewen: bool = False,
    model: str | None = None,
    on_reason: Callable[[str], None] | None = None,
    on_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """生成选题候选。章节数与每章字数是硬输入，缺了直接报 400。"""
    try:
        chapters = int(target_chapters or 0)
        words = int(words_per_chapter or 0)
    except (TypeError, ValueError) as e:
        raise ValueError("目标章节数和章节字数必须是数字") from e
    if chapters <= 0:
        raise ValueError("目标章节数是必填，至少 1 章")
    if chapters > 5000:
        raise ValueError("目标章节数最多 5000")
    if words < 200:
        raise ValueError("章节字数是必填，且每章至少 200 字")
    if words > 50000:
        raise ValueError("每章字数最多 50000")

    n = _normalize_count(count)
    avoid_list = [_text(x, 120) for x in (avoid or []) if _text(x)]

    messages = _prompt(
        direction=_text(direction, 500),
        genre=_text(genre, 60),
        logline=_text(logline, 200),
        platform=platform,
        target_chapters=chapters,
        words_per_chapter=words,
        count=n,
        avoid=avoid_list,
        nuewen=nuewen,
    )
    result = chat(
        messages,
        model=model,
        temperature=0.9,
        max_tokens=6500,
        timeout=300,
        reasoning=reasoning_for("concepts"),
        on_reason=on_reason,
        on_delta=on_delta,
    )
    payload = _extract_json(str(result.get("text") or ""))
    rows = _list_from_payload(payload, "concepts", "items")
    concepts: list[dict[str, Any]] = []
    for i, raw in enumerate(rows):
        cleaned = _clean_concept(raw, i, platform, _text(genre, 40))
        if cleaned:
            concepts.append(cleaned)
        if len(concepts) >= n:
            break
    if not concepts:
        snippet = _text(result.get("text"), 200)
        raise LLMError(f"模型没有返回可解析的选题 JSON。原文片段：{snippet}")

    for i, c in enumerate(concepts):
        if c["id"] in {x["id"] for x in concepts[:i]}:
            c["id"] = f"{c['id']}-{i + 1}"
    return {"concepts": concepts[:n], "model": str(result.get("model") or "")}
