"""开书第三步：从「大纲 + 世界观」拆出可查询的设定。

对应旧插件 setup-gen 的两个入口（人物 / 其余设定），这里合并成一个动作、
内部拆四次模型调用：一次出人物 + 关系 + 信息差，其余设定分三批——
空间（世界/势力/地点）、规则与物品、世界纵深（力量体系/社会/大事记/术语）。
一次全出会顶满输出上限，后半类目直接被截断。

只补不覆盖：bible 里已有同名（含别名）的条目不会覆盖，只补空字段；新名字才新增。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from ..llm import LLMError, chat, strip_fence
from ..store import (
    load_bible,
    load_project,
    project_lock,
    read_chapter,
    read_index,
    save_bible,
    save_project,
)
from .continuity import rule_enforce
from .platforms import platform_brief

CHAR_FIELDS = [
    "rolePosition", "importance", "role", "age", "gender", "race", "callRules",
    "appearance", "personality", "want", "fear", "bottomLine", "flaw", "secret",
    "voice", "ability", "abilityLimit", "abilityCost", "location", "locationAt",
    "currentGoal", "knowledge", "ignorance", "misconception", "status", "firstChapter",
    "exitChapter", "changeLog", "arc", "text",
]
#: 人物字段里是「对象列表」的两个，单独清洗，不走通用字符串分支。
CHAR_LIST_FIELDS = ("locationHistory",)
FACTION_FIELDS = [
    "slang", "nature", "economy", "openRules", "hiddenRules", "relations", "emblem",
    "representatives", "power", "leader", "attitude", "misjudge", "changeLog",
    "state", "stateAt", "text",
]
LOCATION_FIELDS = [
    "spots", "geo", "structure", "senses", "owner", "accessRules", "occupied",
    "state", "stateAt", "events", "familiar", "mapX", "mapY", "terrain", "text",
]
ITEM_FIELDS = [
    "appearance", "origin", "function", "limit", "cost", "type", "holder", "holderAt",
    "location", "state", "stateAt", "whoKnows", "text",
]
ITEM_LIST_FIELDS = ("transferLog",)
RULE_FIELDS = [
    "judge", "enforce", "enforcer", "cost", "boundary", "level", "source", "belief",
    "tested", "exploited", "violationLog", "keywords", "note", "text",
]
# 样章不在这里生成：它由作者选择的作家预设带入（style_presets），或在文风页手填。
STYLE_FIELDS = ["pov", "tense", "banned"]

#: 力量 / 能力体系：修行、异能、魔法、等级、科技分级都落在这里。
POWER_FIELDS = ["name", "summary", "advancement", "costs", "limits", "balance"]
POWER_LEVEL_FIELDS = ["rank", "trait", "gap"]
#: 社会常识：正文里会用来制造冲突、区分阶层与地域的那一层。
SOCIETY_FIELDS = [
    "politics", "economy", "currency", "law", "taboo",
    "customs", "religion", "language", "technology",
]
#: 世界大事记：只收影响当下格局的历史事件。
HISTORY_FIELDS = ["era", "year", "impact"]
#: 术语表：专有名词的统一叫法与含义，防止同物异名。
GLOSSARY_FIELDS = ["meaning", "usage"]

_ENTITY_FIELDS = {
    "world": ["text"],
    "factions": FACTION_FIELDS,
    "locations": LOCATION_FIELDS,
    "items": ITEM_FIELDS,
    "rules": RULE_FIELDS,
}


def _name_key(value: Any) -> str:
    return re.sub(r"[\s·・\-—_/、，,。.（）()「」『』【】]+", "", str(value or "")).lower()


def _text(value: Any, limit: int = 0) -> str:
    s = str(value or "").strip()
    return s[:limit].strip() if limit and len(s) > limit else s


def _extract_object(text: str) -> dict[str, Any] | None:
    s = strip_fence(text or "").strip()
    try:
        value = json.loads(s)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(s[start:end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return _salvage_object(s)


_ARRAY_KEYS = (
    "characters", "relations", "infoGaps", "world", "factions", "locations",
    "items", "rules", "history", "glossary",
)


def _complete_objects(s: str, start: int) -> list[dict[str, Any]]:
    """从 s[start]（应为 '[' 或 '{'）起，按大括号配对收集完整的 JSON 对象。"""
    out: list[dict[str, Any]] = []
    i = s.find("[", start)
    obj_start = s.find("{", start)
    if i < 0 and obj_start < 0:
        return out
    pos = i + 1 if i >= 0 and (obj_start < 0 or i < obj_start) else obj_start
    while pos < len(s):
        while pos < len(s) and s[pos] not in "{]":
            pos += 1
        if pos >= len(s) or s[pos] == "]":
            break
        begin = pos
        depth = 0
        in_str = False
        escaped = False
        while pos < len(s):
            ch = s[pos]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(s[begin:pos + 1])
                        if isinstance(value, dict):
                            out.append(value)
                    except json.JSONDecodeError:
                        pass
                    pos += 1
                    break
            pos += 1
        else:
            break
    return out


def _salvage_object(s: str) -> dict[str, Any] | None:
    """模型输出被 max_tokens 截断时，把前面完整的条目抢救出来，不让整轮白跑。"""
    out: dict[str, Any] = {}
    for key in _ARRAY_KEYS:
        m = re.search(rf'"{key}"\s*:\s*\[', s)
        if not m:
            continue
        items = _complete_objects(s, m.end() - 1)
        if items:
            out[key] = items
    for key in ("style", "powerSystem", "society"):
        m = re.search(rf'"{key}"\s*:\s*\{{', s)
        if not m:
            continue
        begin = m.end() - 1
        depth = 0
        in_str = False
        escaped = False
        for i in range(begin, len(s)):
            ch = s[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(s[begin:i + 1])
                        if isinstance(value, dict):
                            out[key] = value
                    except json.JSONDecodeError:
                        pass
                    break
    return out or None


Delta = Callable[[str], None]
Stage = Callable[[str], None]


def _chat_object(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    max_tokens: int,
    timeout: float,
    on_delta: Delta | None = None,
    on_stage: Stage | None = None,
    label: str = "设定",
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """调一次模型并解析 JSON；格式不对时换一次请求重试，别让整轮白跑。

    只有「解析失败」才重试：网络 / HTTP 错误照旧抛出，流式已经吐过字的也不重试，
    否则同一段内容会在前端出现两遍。

    返回 ``(解析后的对象, 原始响应, 最终一次输出的全文)``；全文给并发场景用——
    增量是各跑各的，完成时要把整段补进流里。
    """
    last = ""
    for attempt in (1, 2):
        try:
            result = chat(
                messages, model=model, temperature=0.5, max_tokens=max_tokens,
                timeout=timeout, reasoning="low",
                on_delta=on_delta if attempt == 1 else None,
            )
        except LLMError as e:
            if attempt == 2:
                raise
            if on_stage:
                on_stage(f"{label} · 模型失败，重试")
            if on_delta:
                on_delta(f"\n── {label} · 重试 ──\n")
            last = str(e)
            continue
        last = str(result.get("text") or "")
        obj = _extract_object(last)
        if obj is not None:
            return obj, result, last
        if attempt == 1:
            if on_stage:
                on_stage(f"{label} · 格式不对，重试")
            if on_delta:
                on_delta(f"\n── {label} · 格式不对，重试 ──\n")
    raise LLMError(f"模型没有返回可解析的{label} JSON。原文片段：{_text(last, 200)}")


def _section(on_stage: Stage | None, on_delta: Delta | None, label: str) -> None:
    """换一个模型调用时，在流里也标一段小标题，作者能看清现在拆到哪一类。"""
    if on_stage:
        on_stage(label)
    if on_delta:
        on_delta(f"\n── {label} ──\n")


def _dict_brief(value: Any, fields: tuple[tuple[str, str], ...], limit: int = 70) -> str:
    if not isinstance(value, dict):
        return "（无）"
    bits = [f"{label}:{_text(value.get(key), limit)}" for key, label in fields if _text(value.get(key))]
    levels = [x for x in (value.get("levels") or []) if isinstance(x, dict) and _text(x.get("name"))]
    if levels:
        bits.append("等级:" + "→".join(_text(x.get("name"), 20) for x in levels[:12]))
    return "；".join(bits) or "（无）"


def _rows_brief(rows: list[Any], id_field: str, fields: tuple[str, ...], limit: int = 60) -> str:
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get(id_field), 50)
        if not name:
            continue
        bits = [f"{f}:{_text(row.get(f), limit)}" for f in fields if _text(row.get(f))]
        out.append(f"- {name}" + (f"｜{'｜'.join(bits)}" if bits else ""))
    return "\n".join(out) or "（无）"


def _material(project: dict[str, Any], bible: dict[str, Any], *, chars_only: bool) -> str:
    outline = str(project.get("outlineText") or "").strip()
    world = str(project.get("worldText") or "").strip()
    if len(outline) > 11000:
        outline = outline[:11000] + "\n…（大纲后段从略）"
    if len(world) > 5000:
        world = world[:5000] + "\n…（世界观后段从略）"

    def brief(rows: list[dict[str, Any]], fields: list[str]) -> str:
        out = []
        for row in rows[:80]:
            name = _text(row.get("name"), 30)
            if not name:
                continue
            alias = row.get("aliases")
            bits = [f"又叫:{'、'.join(alias)}"] if isinstance(alias, list) and alias else []
            if not chars_only:
                for f in fields:
                    v = row.get(f)
                    if isinstance(v, list) and v:
                        bits.append(f"{f}:{'、'.join(str(x) for x in v)[:60]}")
                    elif v not in (None, "", []):
                        bits.append(f"{f}:{_text(v, 60)}")
            out.append(f"- {name}" + (f"｜{'｜'.join(bits)}" if bits else ""))
        return "\n".join(out) or "（无）"

    parts = [
        f"书名：{project.get('title') or '未命名'}；题材：{project.get('genre') or '未定'}；"
        f"平台：{project.get('platform') or '通用'}",
        "",
        "【故事梗概】",
        _text(project.get("synopsis"), 900) or "（空）",
        "",
        "【大纲】",
        outline or "（空）",
        "",
        "【世界观】",
        world or "（空）",
    ]
    if chars_only:
        parts += [
            "",
            "【已有的人物（同名算同一个人：只为它补空字段，不要覆盖已有值）】",
            brief(bible.get("characters") or [], [
                "rolePosition", "importance", "gender", "age", "race", "personality",
                "status", "location", "locationAt", "firstChapter", "exitChapter",
            ]),
        ]
    else:
        parts += [
            "",
            "【已有设定（同名/别名一律不新增；可补空字段）】",
            "势力：", brief(bible.get("factions") or [], ["state", "stateAt", "attitude", "text"]),
            "地点：", brief(bible.get("locations") or [], ["state", "stateAt", "occupied", "text"]),
            "物品：", brief(bible.get("items") or [], ["holder", "state", "text"]),
            "规则：", brief(bible.get("rules") or [], ["enforce", "text", "cost"]),
            "力量体系：", _dict_brief(bible.get("powerSystem"), (
                ("name", "名"), ("summary", "总结"), ("advancement", "晋升"),
                ("costs", "代价"), ("limits", "上限"), ("balance", "平衡"),
            )),
            "社会常识：", _dict_brief(bible.get("society"), (
                ("politics", "政治"), ("economy", "经济"), ("currency", "货币"),
                ("law", "律法"), ("taboo", "禁忌"), ("customs", "风俗"),
                ("religion", "宗教"), ("language", "语言"), ("technology", "技术"),
            )),
            "大事记：", _rows_brief(bible.get("history") or [], "event", ("era", "year", "impact")),
            "术语：", _rows_brief(bible.get("glossary") or [], "term", ("meaning", "usage")),
            "",
            "【已有的人物（只列名字和位置，这一轮不改人物）】",
            brief(bible.get("characters") or [], ["location", "status"]),
        ]
    return "\n".join(parts)


def _char_messages(project: dict[str, Any], bible: dict[str, Any]) -> list[dict[str, str]]:
    system = "\n".join([
        "你是中文网文的人物档案员。大纲和世界观已经定了，你的工作是把里面的人物拆成能查、能对照的档案。",
        "你不改大纲，不写正文，也不碰势力/地点/物品/规则/文风。只输出 JSON，不要解释。",
        "",
        "硬性要求：",
        "1. 素材里出现的人名、称呼都要收进人物表；只有称呼没有名字的，用大纲里最常用的写法当 name。",
        "2. 已有条目（含别名、外号、职务称呼）算同一个人：输出时 name 用已有写法，只补它的空字段，不要改已有值。",
        "2b. aliases 必须写全：外号、小名、化名、江湖名号、他人惯用称呼、正文里会用来指代他的称呼都收进来；",
        "    正文里只要用了其中一个称呼，体检和人物识别都要能对上这个人。确实没有别名就留空，不要拿本名充数。",
        "3. 每个人物必须写 rolePosition（主角/女主/反派/常驻配角/单卷配角/工具人）和 importance（核心/主要/次要/龙套）。",
        "   核心=主角与核心 3–5 人（全字段）；主要=常驻配角；次要=单卷功能角色；龙套=只登记名字。不要把所有人都写成核心。",
        "4. 人物卡的最低信息：性别、年龄、种族/身份、性格、重要程度、首次出场章、出场状态（在场/失踪/死亡/退场）、",
        "   截至首次出场时的所在地。素材没写就别硬填，留空比编造好；但能在世界观里推出来的（如种族、职业）要填。",
        "5. 性格只写一句行为倾向（例如「遇事先算账，嘴上不饶人」），不要堆形容词。",
        "6. 位置写 location（地名，与地点表统一叫法）；locationAt 写这个位置截至第几章有效（还没写正文就用首次出场章）。",
        "   不要编造还没发生的移动轨迹，locationHistory 留给正文回写。",
        "7. relations 是必交项：素材里写明的每一对关键人物关系都要出一条（a→b，state 写当前状态，如「师徒但彼此提防」「欠一条命」）。",
        "8. infoGaps 是必交项：素材里写明的每个关键秘密都要出一条，写清谁知道、谁不知道、谁以为自己知道。",
        "9. 每个人物的 knowledge / ignorance / misconception 写「他知道什么 / 他不知道什么 / 他误以为什么」，这是写正文制造信息差用的。",
        "10. 新增人物控制在 12 人以内。",
        "",
        "输出 JSON 结构：",
        "{",
        '  "characters":[{"name":"","rolePosition":"主角|女主|反派|常驻配角|单卷配角|工具人",'
        '"importance":"核心|主要|次要|龙套","aliases":[],"callRules":"","role":"","age":"","gender":"","race":"",'
        '"appearance":"","personality":"","want":"","fear":"","bottomLine":"","flaw":"","secret":"","voice":"",'
        '"ability":"","abilityLimit":"","abilityCost":"","location":"","locationAt":null,'
        '"currentGoal":"","knowledge":"","ignorance":"","misconception":"",'
        '"changeLog":"","status":"active|dead|missing|exited",'
        '"firstChapter":null,"exitChapter":null,"text":"一句话定位"}],',
        '  "relations":[{"a":"","b":"","state":"","note":""}],',
        '  "infoGaps":[{"secret":"","knows":"","doesntKnow":"","thinksKnows":""}]',
        "}",
        "值为空的键直接不要输出，不要写 \"\"、[]、null 占位。",
    ])
    user = "\n".join([
        "以下是这本书的素材与已有的人物，请补齐人物档案，只输出 JSON：",
        "",
        "<素材>",
        _material(project, bible, chars_only=True),
        "</素材>",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _setup_messages(project: dict[str, Any], bible: dict[str, Any], only: list[str]) -> list[dict[str, str]]:
    system = "\n".join([
        "你是中文网文的设定补全员。大纲和世界观已经定了，你的工作是把它们拆成一条条能查、能对照的设定。",
        "你不改大纲，不写正文，也不碰人物。只输出本次范围的类别"
        "（世界/势力/地点/物品/规则/力量体系/社会常识/大事记/术语/文风），只输出 JSON。",
        "",
        "硬性要求：",
        "1. 大纲只负责结构，世界观只负责叙事；可执行的势力、地点、物品、规则由你从这两份素材里拆出来。素材里没有现成规则清单是正常的，不要因此不写规则。",
        "2. 只写大纲/世界观能支撑的内容；推不出的字段留空，不要编造。",
        "3. 规则是「这个世界怎么运转」的条文，不只有不能违反的铁律，要按可违反程度分类，写进 enforce：",
        "   铁律=不可违反，破了人物或世界就不成立，只能绕；",
        "   契约=可以违反，但必须当场付出明确代价（反噬、折寿、失忆、违约反扑）；",
        "   惯例=可以违反，代价是社会性的（被逐出、失去信誉、得罪势力）；",
        "   谣言=人物以为是规则，其实不成立，打破后要揭示真相。",
        "   每条规则都要能被正文里的具体句子验证；写清 enforce / cost / boundary（什么时候不适用、漏洞在哪）/ enforcer（谁在执行）。",
        "4. 四类都要有：一个世界全是铁律会没有余地，全是惯例会没有压力。",
        "5. 物品只收「后面还会被提到、使用、追查」的；一次性道具不要写。每件物品必须有当前持有人（holder）和状态（state）。",
        "6. 势力盯潜规则与对主角的误判，地点盯地图与进出规矩，物品盯持有人与状态。",
        "6a. 势力与地点都要写当前状态 state 和截至章 stateAt（如「受创但仍在配给」「被船行会接管」，stateAt=3）；",
        "    势力另写 attitude（对主角的当前态度），地点另写 occupied（现在被谁占着）。状态会随剧情变化，不要只写静态介绍。",
        "6b. 地点名要带空间层级词，地图按名字排层：核心（登记室/册房）、内舱、中区、外墙、城外（废墟/新城）逐层往外；",
        "    geo 里写清它在这一层的哪一侧（东/南/西/北）。terrain 写城|镇|村|山林|水岸|废墟|关隘|营地 之一，",
        "    mapX/mapY 可留 0，只作参考，地图不再按坐标画地形。",
        "7. 已有同名（含别名/简称）的条目不会覆盖：输出同名条目时只补空字段。",
        "8. 新增条目控制在：势力≤6、地点≤6、物品≤6、规则≤8、世界≤4、大事记≤10、术语≤20。",
        "9. style 只在素材能支撑时给，pov/tense/banned 都可以为空；不要输出 samples（样章由作者选的作家预设带入）。",
        "10. 力量体系 powerSystem：世界观里若有修行、异能、魔法、等级、科技分级，必须拆出来——",
        "    总名、一句话总结、等级台阶（每级写名字/位阶/特征/和上一级的差距）、晋升方式、代价、上限、平衡点。",
        "    没有超自然力量就输出 {}，不要硬造一套。",
        "11. 大事记 history：只收影响当下格局的历史事件（战争、灾变、王朝更替、封印、条约），",
        "    每条写清时代、年份、事件、对现在的影响；不要写编年史流水账。",
        "12. 社会常识 society：政治、经济、货币、律法、禁忌、风俗、宗教、语言、技术；",
        "    只写正文会用到、能制造冲突或区分阶层/地域的部分。",
        "13. 术语 glossary：功法、组织黑话、称号、器物类别、度量等专有名词写清含义和正文用法，防止同物异名。",
        "",
        "输出 JSON 结构：",
        "{",
        '  "world":[{"name":"","text":""}],',
        '  "factions":[{"name":"","aliases":[],"slang":"","nature":"","economy":"","openRules":"",'
        '"hiddenRules":"","relations":"","emblem":"","representatives":"","power":"","leader":"",'
        '"attitude":"","misjudge":"","state":"","stateAt":null,"text":""}],',
        '  "locations":[{"name":"","aliases":[],"geo":"","structure":"","senses":"","owner":"",'
        '"accessRules":"","occupied":"","state":"","stateAt":null,"events":"","familiar":"",'
        '"mapX":0,"mapY":0,"terrain":"","text":""}],',
        '  "items":[{"name":"","aliases":[],"appearance":"","origin":"","function":"","limit":"",'
        '"cost":"","type":"伏笔型|功能型|氛围型","holder":"","holderAt":null,"location":"","state":"",'
        '"stateAt":null,"whoKnows":"","text":""}],',
        '  "rules":[{"name":"","text":"用世界里的话写规则条文","enforce":"铁律|契约|惯例|谣言",'
        '"enforcer":"谁在执行/监督","cost":"违反会怎样","boundary":"什么时候不适用/漏洞在哪",'
        '"source":"","belief":"","keywords":["触发关键词"]}],',
        '  "powerSystem":{"name":"","summary":"","levels":[{"name":"","rank":"","trait":"","gap":""}],'
        '"advancement":"怎么晋升","costs":"用什么换","limits":"上限与做不到的事","balance":"为什么强者没有通吃"},',
        '  "society":{"politics":"","economy":"","currency":"","law":"","taboo":"","customs":"",'
        '"religion":"","language":"","technology":""},',
        '  "history":[{"era":"","year":"","event":"","impact":"对现在的影响"}],',
        '  "glossary":[{"term":"","meaning":"","usage":"正文里怎么用"}],',
        '  "style":{"pov":"","tense":"","banned":[]}',
        "}",
        "值为空的键直接不要输出，不要写 \"\"、[]、null 占位。",
    ])
    user = "\n".join([
        "以下是这本书的素材与已有设定，请补齐缺失的设定，只输出 JSON：",
        "",
        "<素材>",
        _material(project, bible, chars_only=False),
        "</素材>",
        "",
        platform_brief(project.get("platform")),
        "",
        f"本次只输出 {' / '.join(only)}，其它类别一律不要输出。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _known(bible: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in bible.get(key) or []:
        if not isinstance(row, dict):
            continue
        name = _name_key(row.get("name"))
        if name:
            out[name] = row
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            for a in aliases:
                k = _name_key(a)
                if k:
                    out.setdefault(k, row)
    return out


def _split_chapter(s: str) -> tuple[int, str]:
    """「第3章 到了码头」→ (3, "到了码头")；没有章号就返回 (0, 原文)。"""
    m = re.match(r"^第\s*(\d+)\s*章[\s·:：-]*(.*)$", s)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return 0, s


def _clean_place_log(value: Any) -> list[dict[str, Any]]:
    """locationHistory：允许 [{chapter, place, note}] 或 ["第3章 到了码头"]。"""
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            place = _text(item.get("place") or item.get("to"), 40)
            if not place:
                continue
            chapter, place = _split_chapter(place)
            row = {"chapter": int(item.get("chapter") or chapter), "place": place}
            if _text(item.get("note")):
                row["note"] = _text(item.get("note"), 120)
            out.append(row)
        elif _text(item):
            chapter, place = _split_chapter(_text(item, 40))
            if place:
                out.append({"chapter": chapter, "place": place})
    return out[:40]


def _clean_transfer_log(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            to = _text(item.get("to") or item.get("holder"), 40)
            if not to:
                continue
            chapter, to = _split_chapter(to)
            row = {"chapter": int(item.get("chapter") or chapter), "to": to}
            if _text(item.get("from")):
                row["from"] = _text(item.get("from"), 40)
            if _text(item.get("note")):
                row["note"] = _text(item.get("note"), 120)
            out.append(row)
        elif _text(item):
            chapter, to = _split_chapter(_text(item, 40))
            if to:
                out.append({"chapter": chapter, "to": to})
    return out[:40]


def _clean_list(value: Any, fields: list[str], list_fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 40)
        if not name:
            continue
        row: dict[str, Any] = {"name": name}
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            al = [_text(x, 40) for x in aliases if _text(x)]
            if al:
                row["aliases"] = al
        for f in fields:
            v = item.get(f)
            if isinstance(v, list):
                lst = [_text(x, 80) for x in v if _text(x)]
                if lst:
                    row[f] = lst
            elif isinstance(v, (int, float)):
                row[f] = v
            elif v not in (None, ""):
                row[f] = _text(v, 400)
        for f in list_fields:
            if f == "locationHistory":
                hist = _clean_place_log(item.get(f))
            else:
                hist = _clean_transfer_log(item.get(f))
            if hist:
                row[f] = hist
        if ("enforce" in fields or "level" in fields) and (item.get("enforce") or item.get("level")):
            row["enforce"] = rule_enforce(item)
        out.append(row)
    return out


def _clean_object(value: Any, fields: list[str]) -> dict[str, Any]:
    """对象型设定（社会常识 / 力量体系）：只留非空字段，长文本截断。"""
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for f in fields:
        v = value.get(f)
        if isinstance(v, list):
            lst = [_text(x, 100) for x in v if _text(x)]
            if lst:
                out[f] = lst
        elif v not in (None, ""):
            out[f] = _text(v, 600)
    return out


def _clean_power(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out = _clean_object(value, [f for f in POWER_FIELDS if f != "levels"])
    levels: list[dict[str, Any]] = []
    for item in value.get("levels") if isinstance(value.get("levels"), list) else []:
        if isinstance(item, dict):
            name = _text(item.get("name"), 40)
            if not name:
                continue
            level: dict[str, Any] = {"name": name}
            for f in POWER_LEVEL_FIELDS:
                if _text(item.get(f)):
                    level[f] = _text(item.get(f), 240)
            levels.append(level)
        elif _text(item):
            levels.append({"name": _text(item, 40)})
    if levels:
        out["levels"] = levels[:24]
    return out


def _clean_history(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            event = _text(item.get("event") or item.get("name"), 180)
            if not event:
                continue
            row: dict[str, Any] = {"event": event}
            for f in HISTORY_FIELDS:
                if _text(item.get(f)):
                    row[f] = _text(item.get(f), 300)
            out.append(row)
        elif _text(item):
            out.append({"event": _text(item, 180)})
    return out[:60]


def _clean_glossary(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            term = _text(item.get("term") or item.get("name"), 50)
            if not term:
                continue
            row: dict[str, Any] = {"term": term}
            for f in GLOSSARY_FIELDS:
                if _text(item.get(f)):
                    row[f] = _text(item.get(f), 300)
            out.append(row)
        elif _text(item):
            out.append({"term": _text(item, 50)})
    return out[:120]


def _merge_object(
    bible: dict[str, Any],
    key: str,
    patch: dict[str, Any],
    fields: list[str],
) -> tuple[int, int]:
    """对象型设定只补不覆盖；力量等级按名字追加。返回 (新增, 补齐)。"""
    if not patch:
        return 0, 0
    cur = bible.get(key) if isinstance(bible.get(key), dict) else {}
    merged = dict(cur)
    changed = False
    for f in fields:
        if f == "levels":
            continue
        if merged.get(f) in (None, "", []) and patch.get(f) not in (None, "", []):
            merged[f] = patch[f]
            changed = True
    if key == "powerSystem" and patch.get("levels"):
        levels = [x for x in (merged.get("levels") or []) if isinstance(x, dict)]
        seen = {_name_key(x.get("name")) for x in levels}
        for level in patch["levels"]:
            nk = _name_key(level.get("name"))
            if nk and nk not in seen:
                levels.append(level)
                seen.add(nk)
                changed = True
        if levels:
            merged["levels"] = levels[:24]
    if not changed:
        return 0, 0
    bible[key] = merged
    return (0, 1) if cur else (1, 0)


def _merge_rows(
    bible: dict[str, Any],
    key: str,
    rows: list[dict[str, Any]],
    id_field: str,
    fields: list[str],
    limit: int,
) -> tuple[int, int, int]:
    """列表型设定按 id_field（event / term）去重：新的追加，旧的只补空字段。"""
    cur = [x for x in (bible.get(key) or []) if isinstance(x, dict)]
    known = {_name_key(x.get(id_field)): x for x in cur if _name_key(x.get(id_field))}
    added = filled = skipped = 0
    for row in rows:
        nk = _name_key(row.get(id_field))
        if not nk:
            continue
        if nk in known:
            target = {f: row.get(f) for f in fields if row.get(f) not in (None, "")}
            if _fill_missing(known[nk], target):
                filled += 1
            else:
                skipped += 1
            continue
        cur.append(row)
        known[nk] = row
        added += 1
    if added:
        bible[key] = cur[:limit]
    return added, filled, skipped


def _fill_missing(row: dict[str, Any], patch: dict[str, Any]) -> int:
    """只补空字段：已有值一个字都不动。返回补了几个字段。"""
    filled = 0
    for key, value in patch.items():
        if key in ("name", "aliases"):
            continue
        cur = row.get(key)
        if cur in (None, "", []):
            row[key] = value
            filled += 1
        elif key == "enforce" and not row.get("level"):
            row["level"] = value
    return filled


def _apply_bible(
    bible: dict[str, Any],
    char_obj: dict[str, Any],
    setup_obj: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """把模型输出并进 bible：新名字新增；同名（含别名）只补空字段，不覆盖。

    返回 ``(added, skipped, filled)``。
    """
    added = {
        "characters": 0, "world": 0, "factions": 0, "locations": 0, "items": 0, "rules": 0,
        "powerSystem": 0, "society": 0, "history": 0, "glossary": 0,
    }
    skipped = dict.fromkeys(added, 0)
    filled = dict.fromkeys(added, 0)

    known_chars = _known(bible, "characters")
    for row in _clean_list(char_obj.get("characters"), CHAR_FIELDS, CHAR_LIST_FIELDS):
        key = _name_key(row.get("name"))
        if not key:
            continue
        if key in known_chars:
            if _fill_missing(known_chars[key], row):
                filled["characters"] += 1
            else:
                skipped["characters"] += 1
            continue
        bible.setdefault("characters", []).append(row)
        known_chars[key] = row
        added["characters"] += 1

    for key in ("world", "factions", "locations", "items", "rules"):
        known = _known(bible, key)
        list_fields = ITEM_LIST_FIELDS if key == "items" else ()
        for row in _clean_list(setup_obj.get(key), _ENTITY_FIELDS[key], list_fields):
            nk = _name_key(row.get("name"))
            if not nk:
                continue
            if nk in known:
                if _fill_missing(known[nk], row):
                    filled[key] += 1
                else:
                    skipped[key] += 1
                continue
            bible.setdefault(key, []).append(row)
            known[nk] = row
            added[key] += 1

    # 力量体系 / 社会常识：对象型，只补空字段；等级按名字追加。
    p_added, p_filled = _merge_object(
        bible, "powerSystem", _clean_power(setup_obj.get("powerSystem")),
        POWER_FIELDS + ["levels"],
    )
    added["powerSystem"] += p_added
    filled["powerSystem"] += p_filled
    s_added, s_filled = _merge_object(
        bible, "society", _clean_object(setup_obj.get("society"), SOCIETY_FIELDS),
        SOCIETY_FIELDS,
    )
    added["society"] += s_added
    filled["society"] += s_filled

    # 大事记 / 术语表：列表型，按 event / term 去重。
    h_added, h_filled, h_skipped = _merge_rows(
        bible, "history", _clean_history(setup_obj.get("history")),
        "event", HISTORY_FIELDS, 60,
    )
    added["history"] += h_added
    filled["history"] += h_filled
    skipped["history"] += h_skipped
    g_added, g_filled, g_skipped = _merge_rows(
        bible, "glossary", _clean_glossary(setup_obj.get("glossary")),
        "term", GLOSSARY_FIELDS, 120,
    )
    added["glossary"] += g_added
    filled["glossary"] += g_filled
    skipped["glossary"] += g_skipped

    # 关系矩阵：a→b 去重，只新增；已有的一对不覆盖
    if isinstance(char_obj.get("relations"), list):
        seen = {
            (_name_key(r.get("a")), _name_key(r.get("b")))
            for r in (bible.get("relations") or []) if isinstance(r, dict)
        }
        for item in char_obj["relations"]:
            if not isinstance(item, dict):
                continue
            a, b = _text(item.get("a"), 40), _text(item.get("b"), 40)
            state, note = _text(item.get("state"), 120), _text(item.get("note"), 160)
            if not a or not b or a == b or not (state or note):
                continue
            k = (_name_key(a), _name_key(b))
            if k in seen:
                continue
            seen.add(k)
            bible.setdefault("relations", []).append({"a": a, "b": b, "state": state, "note": note})

    if isinstance(char_obj.get("infoGaps"), list):
        seen_gaps = {_name_key(g.get("secret")) for g in (bible.get("infoGaps") or []) if isinstance(g, dict)}
        for item in char_obj["infoGaps"]:
            if not isinstance(item, dict):
                continue
            secret = _text(item.get("secret"), 160)
            if not secret or _name_key(secret) in seen_gaps:
                continue
            seen_gaps.add(_name_key(secret))
            bible.setdefault("infoGaps", []).append({
                "secret": secret,
                "knows": _text(item.get("knows"), 160),
                "doesntKnow": _text(item.get("doesntKnow"), 160),
                "thinksKnows": _text(item.get("thinksKnows"), 160),
            })

    style = setup_obj.get("style") if isinstance(setup_obj.get("style"), dict) else {}
    if style:
        cur = bible.get("style") if isinstance(bible.get("style"), dict) else {}
        patch = dict(cur)
        for f in STYLE_FIELDS:
            v = style.get(f)
            empty = cur.get(f) in (None, "", [])
            if f == "banned":
                if empty and isinstance(v, list) and v:
                    patch[f] = [_text(x, 200) for x in v if _text(x)]
            elif empty and v not in (None, ""):
                patch[f] = _text(v, 120)
        # samples 永远不从这里写：样章来自 style_presets，避免模型编一段“示范文”冒充原文。
        bible["style"] = patch

    return added, skipped, filled


def _run_job(
    messages: list[dict[str, str]],
    *,
    model: str | None,
    max_tokens: int,
    label: str,
    timeout: float = 420,
) -> dict[str, Any]:
    """跑一路设定调用，增量先攒在本地，完成时整段交给主线程。

    四路并发时若把各路的 ``on_delta`` 直接转给 SSE，四份 JSON 会交错成一段乱码；
    所以这里只收集，由主线程按「谁先完成谁先显示」整块输出。
    """
    chunks: list[str] = []
    notes: list[str] = []
    try:
        obj, result, text = _chat_object(
            messages, model=model, max_tokens=max_tokens, timeout=timeout,
            on_delta=chunks.append, on_stage=notes.append, label=label,
        )
    except Exception as e:  # noqa: BLE001 — 交给主线程汇总后再决定抛不抛
        return {"notes": notes, "text": "".join(chunks), "error": e}
    return {"notes": notes, "text": text or "".join(chunks), "obj": obj, "result": result}


def generate_settings(
    root: str | os.PathLike,
    *,
    model: str | None = None,
    on_delta: Delta | None = None,
    on_stage: Stage | None = None,
) -> dict[str, Any]:
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    if not str(project.get("outlineText") or "").strip() and not str(project.get("worldText") or "").strip():
        raise ValueError("还没有大纲和世界观：先在「开书」页生成大纲+世界观，再补设定")
    bible = load_bible(root)

    # 一次全类别输出会顶满输出上限（规则最容易在后半被截断），分三批：空间 / 规则与物品 / 世界纵深。
    # 四批互不依赖（都只读同一份素材快照），并发跑：原来串行 2–3 分钟，并发约 1 分钟。
    batches = (
        (["world", "factions", "locations"], "拆势力与地点"),
        (["items", "rules", "style"], "拆物品与规则"),
        (["powerSystem", "society", "history", "glossary"], "拆世界纵深"),
    )
    jobs: list[tuple[str, str, str, list[dict[str, str]], int]] = [
        ("characters", "拆人物档案", "人物", _char_messages(project, bible), 12000),
    ]
    jobs += [
        (label, label, label.replace("拆", ""), _setup_messages(project, bible, only), 9000)
        for only, label in batches
    ]

    if on_stage:
        on_stage("四路并行拆设定：人物 / 势力地点 / 物品规则 / 世界纵深")
    parts: dict[str, dict[str, Any]] = {}
    errors: list[tuple[str, Exception]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_run_job, messages, model=model, max_tokens=max_tokens, label=short): section
            for _, section, short, messages, max_tokens in jobs
        }
        for future in as_completed(futures):
            section = futures[future]
            out = future.result()
            for note in out["notes"]:
                if on_stage:
                    on_stage(note)
            if out.get("error") is not None:
                errors.append((section, out["error"]))
                if on_stage:
                    on_stage(f"{section} · 失败")
                if on_delta and out["text"]:
                    on_delta(f"\n── {section} · 失败，模型原文 ──\n{out['text']}\n")
                continue
            parts[section] = out
            if on_stage:
                on_stage(f"{section} · 完成")
            if on_delta:
                on_delta(f"\n── {section} ──\n{out['text']}\n")
    if errors:
        detail = "；".join(f"{section}：{err}" for section, err in errors)
        raise LLMError(f"设定没拆完（{detail}）。已成功的几路没有写入，重跑一次即可。")

    char_obj = parts["拆人物档案"]["obj"]
    char_result = parts["拆人物档案"]["result"]
    setup_obj: dict[str, Any] = {
        "world": [], "factions": [], "locations": [], "items": [], "rules": [],
        "powerSystem": {}, "society": {}, "history": [], "glossary": [], "style": {},
    }
    setup_model = ""
    for only, label in batches:
        part = parts[label]["obj"]
        setup_model = setup_model or str(parts[label]["result"].get("model") or "")
        for key in only:
            if key in ("powerSystem", "society", "style") and isinstance(part.get(key), dict):
                setup_obj[key] = {**setup_obj[key], **part[key]}
            elif isinstance(part.get(key), list):
                setup_obj[key].extend(part[key])

    if on_stage:
        on_stage("整理设定")
    with project_lock(root):
        bible = load_bible(root)
        added, skipped, filled = _apply_bible(bible, char_obj, setup_obj)
        save_bible(root, bible)

        current = load_project(root) or project
        current["gate"] = {
            "phase": "planning",
            "chapter": max(1, int(current.get("currentChapter") or 0) + 1),
            "reason": "设定已就位，下一步设计伏笔 / 草蛇灰线",
            "at": _now(),
        }
        current["settingsAt"] = _now()
        save_project(root, current)

    total = sum(added.values())
    filled_total = sum(filled.values())
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "filled": filled,
        "total": total,
        "bible": load_bible(root),
        "model": setup_model or str(char_result.get("model") or ""),
        "summary": (
            f"新增 {total} 条设定（人物{added['characters']}/势力{added['factions']}/地点{added['locations']}"
            f"/物品{added['items']}/规则{added['rules']}/世界{added['world']}"
            f"/力量体系{added['powerSystem']}/社会{added['society']}/大事记{added['history']}/术语{added['glossary']}）"
            + (f"，补齐 {filled_total} 条已有条目的空字段" if filled_total else "")
        ),
    }


def _known_names(bible: dict[str, Any], key: str, limit: int = 120) -> list[str]:
    """已有条目的名字 + 别名，写进提示词让模型知道什么算「重复」。"""
    out: list[str] = []
    value = bible.get(key)
    rows = [value] if isinstance(value, dict) else (value or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"), 40)
        if name and name not in out:
            out.append(name)
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            for a in aliases:
                s = _text(a, 40)
                if s and s not in out:
                    out.append(s)
        if len(out) >= limit:
            break
    return out[:limit]


def _recent_snippets(root: str | os.PathLike, limit: int = 8) -> list[dict[str, Any]]:
    """最近有正文的几章：优先用回写的摘要，没有摘要就读正文前 600 字。"""
    rows = [r for r in read_index(root) if int(r.get("chars") or 0) > 0 or str(r.get("summary") or "").strip()]
    out: list[dict[str, Any]] = []
    for r in rows[-max(1, limit):]:
        n = int(r.get("number") or 0)
        if n <= 0:
            continue
        summary = re.sub(r"\s+", " ", str(r.get("summary") or "")).strip()
        if not summary:
            try:
                summary = re.sub(r"\s+", " ", read_chapter(root, n) or "").strip()
            except FileNotFoundError:
                summary = ""
        out.append({
            "number": n,
            "title": _text(r.get("title"), 60),
            "summary": summary[:600],
        })
    return out


def _supplement_messages(
    project: dict[str, Any],
    bible: dict[str, Any],
    snippets: list[dict[str, Any]],
) -> list[dict[str, str]]:
    existing = "\n".join(
        f"- {label}：{'、'.join(_known_names(bible, key)) or '（还没有）'}"
        for label, key in (
            ("人物", "characters"), ("势力", "factions"), ("地点", "locations"),
            ("物品", "items"), ("规则", "rules"), ("世界设定", "world"),
            ("力量体系", "powerSystem"), ("大事记", "history"), ("术语", "glossary"),
        )
    )
    chapters = "\n\n".join(
        f"第 {s['number']} 章 {s['title']}\n{s['summary']}" for s in snippets
    )
    system = "\n".join([
        "你是中文网文的设定补全员。正文已经写了一部分，现在只做一件事：",
        "把「正文里已经出现、但设定里还没有」的东西补进设定表。",
        "你不改已有条目、不写新剧情、不预测后续，只输出 JSON。",
        "",
        "硬性要求：",
        "1. 下面「已有清单」里的名字和别名都算已知；同名、简称、称呼一律不要输出。",
        "2. 只收正文里确实出现过的对象，不要根据大纲把还没写到的内容提前写进来。",
        "3. 人物：有名字或被稳定称呼、且已经在场/被提到；要写清这一批正文里的所在地（location）和出场状态（status）；",
        "   正文里用过的外号、称呼写进 aliases（别名算同一个人，不要另起一条）；",
        "   地点：正文里能进去或发生场景的地方；物品：后面还会被提到、使用、追查的，写清当前持有人；",
        "   势力：有组织性和规矩的；规则：跨章一直有效，按 enforce 分铁律/契约/惯例/谣言。",
        "4. 字段能推就写，推不出留空，不要编造。新增上限：人物≤8、地点≤5、物品≤5、势力≤3、规则≤4、术语≤8。",
        "4b. 正文里出现新的力量等级 / 历史事件 / 专有名词时，补 powerSystem.levels、history、glossary；",
        "    社会常识不从正文补（它属于开书时的世界观层）。",
        "5. 没有新增就输出 {}，不要为了凑数硬写。",
        "",
        "输出 JSON 结构（只输出本次新增，或给已有条目补空字段）：",
        "{",
        '  "characters":[{"name":"","aliases":[],"rolePosition":"","importance":"","role":"","gender":"",'
        '"age":"","race":"","personality":"","want":"","fear":"","flaw":"","secret":"","voice":"",'
        '"location":"","status":"active|dead|missing|exited","firstChapter":null,"text":"一句话定位"}],',
        '  "relations":[{"a":"","b":"","state":"","note":""}],',
        '  "infoGaps":[{"secret":"","knows":"","doesntKnow":"","thinksKnows":""}],',
        '  "locations":[{"name":"","aliases":[],"geo":"","structure":"","senses":"","owner":"",'
        '"accessRules":"","occupied":"","state":"","stateAt":null,"events":"","mapX":0,"mapY":0,'
        '"terrain":"","text":""}],',
        '  "items":[{"name":"","aliases":[],"type":"伏笔型|功能型|氛围型","appearance":"","origin":"",'
        '"function":"","limit":"","cost":"","holder":"","state":"","whoKnows":"","text":""}],',
        '  "factions":[{"name":"","aliases":[],"nature":"","openRules":"","hiddenRules":"","relations":"",'
        '"state":"","stateAt":null,"attitude":"","text":""}],',
        '  "rules":[{"name":"","text":"","enforce":"铁律|契约|惯例|谣言","cost":"","boundary":"","keywords":[]}],',
        '  "powerSystem":{"levels":[{"name":"","rank":"","trait":"","gap":""}]},',
        '  "history":[{"era":"","year":"","event":"","impact":""}],',
        '  "glossary":[{"term":"","meaning":"","usage":""}]',
        "}",
        "值为空的键直接不要输出。",
    ])
    user = "\n".join([
        f"书名：{_text(project.get('title'), 60)}｜题材：{_text(project.get('genre'), 40)}｜平台：{_text(project.get('platform'), 40)}",
        "",
        "<已有清单>",
        existing,
        "</已有清单>",
        "",
        f"<最近正文 N={len(snippets)}>",
        chapters,
        "</最近正文>",
        "",
        "请只输出新出现的设定，JSON，不要解释。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def supplement_settings(
    root: str | os.PathLike,
    *,
    recent: int = 8,
    model: str | None = None,
    on_delta: Delta | None = None,
    on_stage: Stage | None = None,
) -> dict[str, Any]:
    """写后补给：从最近正文里抽新人物/地点/物品/势力/规则，同名一律跳过。"""
    project = load_project(root)
    if not project:
        raise ValueError(f"不是小说项目（缺 project.json）：{root}")
    if on_stage:
        on_stage("读最近正文")
    snippets = _recent_snippets(root, recent)
    if not snippets:
        raise ValueError("还没有可读的正文：先写一批，再来补设定")
    bible = load_bible(root)
    _section(on_stage, on_delta, "补新设定")
    obj, result, _ = _chat_object(
        _supplement_messages(project, bible, snippets),
        model=model, max_tokens=8000, timeout=300,
        on_delta=on_delta, on_stage=on_stage, label="补全",
    )

    if on_stage:
        on_stage("整理设定")
    with project_lock(root):
        bible = load_bible(root)
        char_obj = {
            "characters": obj.get("characters"),
            "relations": obj.get("relations"),
            "infoGaps": obj.get("infoGaps"),
        }
        setup_obj = {
            "world": obj.get("world"),
            "factions": obj.get("factions"),
            "locations": obj.get("locations"),
            "items": obj.get("items"),
            "rules": obj.get("rules"),
            "powerSystem": obj.get("powerSystem"),
            "society": obj.get("society"),
            "history": obj.get("history"),
            "glossary": obj.get("glossary"),
        }
        added, skipped, filled = _apply_bible(bible, char_obj, setup_obj)
        total = sum(added.values())
        if total or sum(filled.values()):
            save_bible(root, bible)
        current = load_project(root) or project
        current["supplementAt"] = _now()
        current["updatedAt"] = _now()
        save_project(root, current)

    filled_total = sum(filled.values())
    if total:
        summary = (
            f"补进 {total} 条新设定（人物{added['characters']}/势力{added['factions']}"
            f"/地点{added['locations']}/物品{added['items']}/规则{added['rules']}"
            f"/大事记{added['history']}/术语{added['glossary']}），"
            f"跳过 {sum(skipped.values())} 条重复"
            + (f"，另补齐 {filled_total} 条已有条目的空字段" if filled_total else "")
        )
    elif filled_total:
        summary = f"没有新条目，但给 {filled_total} 条已有设定补了空字段"
    else:
        summary = f"没有新内容：最近 {len(snippets)} 章里的人、地、物设定都已经有了"
    return {
        "ok": True,
        "added": added,
        "skipped": skipped,
        "filled": filled,
        "total": total,
        "chapters": [s["number"] for s in snippets],
        "summary": summary,
        "model": str(result.get("model") or ""),
    }


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
