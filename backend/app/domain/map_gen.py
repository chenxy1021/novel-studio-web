"""按设定里的地点画地图。

地图不做固定排版：提示词由 ``bible.locations`` 生成，模型输出一张独立 SVG，
存进书目录的 ``map.json``。前端只负责展示、重画，排版规则随书变。
"""

from __future__ import annotations

import re
from typing import Any

from ..db import now_iso
from ..llm import chat
from ..store import load_bible, load_project, project_lock, read_json, write_json
from ..store.paths import project_path

MAP_FILE = "map.json"
SVG_LIMIT = 240_000

_FIELDS = (
    ("mapScope", "范围"),
    ("mapLayer", "层级"),
    ("mapBearing", "方位"),
    ("terrain", "地形"),
)


def _text(value: Any, limit: int = 0) -> str:
    s = " ".join(str(value or "").split())
    return s[:limit] if limit and len(s) > limit else s


def _clip(value: Any, limit: int) -> str:
    """保留换行的截断：世界观正文的标题和分段比压成一行更有用。"""
    s = str(value or "").strip()
    return s[:limit].rstrip() if len(s) > limit else s


def _locations(bible: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in (bible.get("locations") or []) if isinstance(x, dict) and _text(x.get("name"))]


def _brief(loc: dict[str, Any], index: int) -> str:
    bits = [f"{index}. {_text(loc.get('name'), 40)}"]
    for key, label in _FIELDS:
        value = _text(loc.get(key), 40)
        if value:
            bits.append(f"{label}:{value}")
    x, y = loc.get("mapX"), loc.get("mapY")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and (x or y):
        bits.append(f"坐标:{x:.0f},{y:.0f}")
    for key, label in (("owner", "归属"), ("geo", "位置"), ("structure", "结构"), ("text", "注释")):
        value = _text(loc.get(key), 160)
        if value:
            bits.append(f"{label}:{value}")
    return " | ".join(bits)


_SOCIETY = (
    ("politics", "政治"), ("economy", "经济"), ("currency", "货币"), ("law", "律法"),
    ("taboo", "禁忌"), ("customs", "风俗"), ("religion", "宗教"),
    ("language", "语言"), ("technology", "技术"),
)


def _world_block(project: dict[str, Any], bible: dict[str, Any]) -> str:
    """地图需要的「世界是什么样」：正文、条目、社会、力量、历史，各取能定结构的。"""
    out: list[str] = []
    text = _clip(project.get("worldText"), 2600)
    if text:
        out.append(text)
    world = [x for x in (bible.get("world") or []) if isinstance(x, dict)]
    rows = [
        "- " + "：".join(v for v in (_text(x.get("name"), 40), _text(x.get("text"), 260)) if v)
        for x in world
        if _text(x.get("name")) or _text(x.get("text"))
    ]
    if rows:
        out.append("世界设定：\n" + "\n".join(rows[:10]))
    society = bible.get("society") if isinstance(bible.get("society"), dict) else {}
    rows = [
        f"- {label}：{_text(society.get(key), 140)}"
        for key, label in _SOCIETY
        if _text(society.get(key))
    ]
    if rows:
        out.append("社会常识：\n" + "\n".join(rows))
    power = bible.get("powerSystem") if isinstance(bible.get("powerSystem"), dict) else {}
    levels = [x for x in (power.get("levels") or []) if isinstance(x, dict)]
    if power:
        bits = [x for x in (
            _text(power.get("name"), 40),
            _text(power.get("summary"), 200),
            "等级：" + " / ".join(_text(x.get("name"), 20) for x in levels[:12] if _text(x.get("name"))) if levels else "",
            _text(power.get("advancement"), 120),
            _text(power.get("limits"), 120),
        ) if x]
        if bits:
            out.append("力量体系：\n" + "\n".join(f"- {b}" for b in bits))
    history = [x for x in (bible.get("history") or []) if isinstance(x, dict)]
    rows = []
    for x in history:
        event = _text(x.get("event"), 120)
        if not event:
            continue
        when = " ".join(v for v in (_text(x.get("era"), 20), _text(x.get("year"), 20)) if v)
        row = f"- {when}：{event}" if when else f"- {event}"
        impact = _text(x.get("impact"), 100)
        rows.append(f"{row}（影响：{impact}）" if impact else row)
    if rows:
        out.append("大事记：\n" + "\n".join(rows[:8]))
    return "\n\n".join(out)


def _messages(project: dict[str, Any], bible: dict[str, Any]) -> list[dict[str, str]]:
    locations = _locations(bible)
    factions = [x for x in (bible.get("factions") or []) if isinstance(x, dict) and _text(x.get("name"))]
    system = "\n".join([
        "你是中文网文的地图绘制师。把这本书设定里的地点排成一张二维示意图，只输出一段独立 SVG。",
        "",
        "硬性要求：",
        "1. 只输出一个完整的 <svg>…</svg>：不要 Markdown 代码块，不要解释，不要 <html>/<body>。",
        '2. 根元素只写 viewBox="0 0 1000 720" xmlns="http://www.w3.org/2000/svg"；不要写 width/height，显示大小交给页面。',
        "3. 自包含：不引用外部图片、字体、CSS、脚本；不要 <script>、<foreignObject>、<image>、on* 事件、javascript: 链接。",
        "4. 每个地点都要出现且只出现一次，写上地名；字号≥14，文字之间不许互相压住，也不许压住边框和标题。",
        "5. 位置只依据给定数据，优先级：坐标(mapX/mapY) > 层级(mapLayer，由内到外) > 范围(mapScope) > 方位(mapBearing) > 位置(geo)。",
        "   数据里没写的距离和地形不要编。",
        "5b. 世界观用来判断世界的整体结构（几块大陆/几层空间/谁和谁接壤/城墙与结界在哪），据此决定画面分区；",
        "    但 <地点> 之外的地名一律不要画，也不要替没写的地方补海岸、山脉、河流。",
        "6. 关系不明时按「范围」分块摆，块与块之间留白、块内均匀排布；没有层级就不要画同心圈。",
        "7. 不要画海岸线、山脉、河流这类设定没写的地形；只画地名、范围边界、势力色、必要的连线。",
        "8. 每个范围用浅色底块或虚线圈起来，并在角上写范围名；有归属的地点用同色标记，图例放右下或左下。",
        '9. 只用 <text> 写中文，font-family="Songti SC, Noto Serif SC, serif"。',
        "10. 配色像手绘设定稿：纸底 #f7f2e7，墨线 #2f2a24，辅助 #8a8072，强调 #b4543f / #3f6d7a / #8a6a2f / #4b6b45。",
        "11. 标题只写一行，放在 y=40 附近；y<78 这条带只给标题，其它文字不要进来。除标题、地名、范围名和图例外不写长句。",
        "12. 设定只给了文字方位时，就按方位摆，不要为了好看挪位置。",
        "13. 图要短：控制在 150 行以内，不写长注释、不重复样式，每个地点一行 <text> 就够。",
        "14. 地名写成独立标签（浅底 + 细边），靠近节点但不压在节点图形或边框上；上下两行文字基线至少隔 22。",
        "15. 底部 y>680 只留给图例，地名不要落到这条带里。",
    ])
    user = "\n".join([
        f"书名：{_text(project.get('title'), 60)}｜题材：{_text(project.get('genre'), 40)}",
        "",
        "<世界观>",
        _world_block(project, bible) or "（无）",
        "</世界观>",
        "",
        "<地点>",
        "\n".join(_brief(loc, i + 1) for i, loc in enumerate(locations)),
        "</地点>",
        "",
        "<势力>",
        "\n".join(
            f"{i + 1}. {_text(f.get('name'), 30)}"
            + (f"｜{_text(f.get('nature'), 60)}" if _text(f.get("nature")) else "")
            for i, f in enumerate(factions)
        ) or "（无）",
        "</势力>",
        "",
        "请输出 SVG。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_BLOCKS = re.compile(r"<\s*(script|foreignObject|iframe|object|embed)\b.*?<\s*/\s*\1\s*>", re.I | re.S)
_EMPTY_BLOCKS = re.compile(r"<\s*(script|foreignObject|iframe|object|embed)\b[^>]*/?>", re.I)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*')", re.I)
_JS_HREF = re.compile(r"(\s(?:xlink:)?href\s*=\s*)(\"|')\s*(?:javascript:|https?:|//)[^\"']*\2", re.I)
_ROOT_SIZE = re.compile(r'\s(?:width|height)="(?:100%|auto)"', re.I)


def normalize_svg(svg: str) -> str:
    """根标签只留 viewBox：``width="100%"`` / ``height="auto"`` 在 <img> 里无效，
    ``height="auto"`` 还会被浏览器当成无效长度报错。比例由 viewBox 定，显示大小交给外层 CSS。"""
    end = svg.find(">")
    if end < 0:
        return svg
    head = svg[: end + 1]
    clean = _ROOT_SIZE.sub("", head)
    return svg if clean == head else clean + svg[end + 1:]


_SVG_RETRY = "上一版没有给出完整的 SVG。不要分析，直接从 <svg 开始，输出一张完整、可闭合的图。"


def draw_svg(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_tokens: int = 16000,
    temperature: float = 0.3,
) -> tuple[str, dict[str, Any]]:
    """让模型画一张 SVG；没画成再要一次，避免作者点一下就吃一个错误。

    只有「没拿到完整 SVG」才重试；网络/额度错误照常抛给上层。
    """
    options = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": 300,
        # 画图不需要长篇思考：思考会吃掉输出预算，SVG 容易半截断掉。
        "reasoning": "none",
    }
    out = chat(messages, **options)
    try:
        return extract_svg(str(out.get("text") or "")), out
    except ValueError:
        retry = chat([*messages, {"role": "user", "content": _SVG_RETRY}], **options)
        return extract_svg(str(retry.get("text") or "")), retry


def extract_svg(text: str) -> str:
    s = (text or "").strip()
    start = s.lower().find("<svg")
    end = s.lower().rfind("</svg>")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 SVG，再画一次试试")
    svg = s[start:end + 6]
    for pattern, repl in ((_BLOCKS, ""), (_EMPTY_BLOCKS, ""), (_ON_ATTR, ""), (_JS_HREF, "")):
        svg = pattern.sub(repl, svg)
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg).strip()
    if not svg.lower().startswith("<svg"):
        raise ValueError("模型返回的 SVG 不完整，再画一次试试")
    # <img> 里的 data URI 必须带命名空间，模型偶尔会漏。
    head = svg[: svg.find(">") + 1]
    if "xmlns=" not in head:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    svg = normalize_svg(svg)
    if len(svg) > SVG_LIMIT:
        raise ValueError("模型返回的图太大，再画一次试试")
    return svg


# 老调用方（测试/脚本）用的是私有名，留着不另起一套。
_extract_svg = extract_svg


def load_map(root: str | Any) -> dict[str, Any]:
    try:
        data = read_json(project_path(root, MAP_FILE))
    except (FileNotFoundError, ValueError):
        return {"svg": "", "at": "", "model": ""}
    if not isinstance(data, dict):
        return {"svg": "", "at": "", "model": ""}
    svg = str(data.get("svg") or "")
    if not svg.lstrip().lower().startswith("<svg"):
        svg = ""
    else:
        # 旧版本存下来的图根标签带 height="auto"；读的时候顺手修掉。
        svg = normalize_svg(svg)
    return {"svg": svg, "at": str(data.get("at") or ""), "model": str(data.get("model") or "")}


def generate_map(root: str | Any, model: str | None = None) -> dict[str, Any]:
    project = load_project(root) or {}
    bible = load_bible(root)
    if len(_locations(bible)) < 2:
        raise ValueError("地点太少：先在设定页从大纲里拆出地点")
    svg, out = draw_svg(_messages(project, bible), model=model, max_tokens=16000)
    doc = {"svg": svg, "at": now_iso(), "model": str(out.get("model") or "")}
    with project_lock(root):
        write_json(project_path(root, MAP_FILE), doc)
    return doc
