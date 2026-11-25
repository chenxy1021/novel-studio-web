"""按设定里的人物与关系画一张关系图。

不固定排版：提示词由 ``bible.characters`` + 已合并的关系生成，模型输出一张
独立 SVG，存进书目录的 ``relation_map.json``。换书只换数据，不换代码。
"""

from __future__ import annotations

from typing import Any

from ..db import now_iso
from ..store import load_bible, load_project, project_lock, read_json, write_json
from ..store.paths import project_path
from .map_gen import draw_svg, normalize_svg
from .memory import effective_relations

RELATION_MAP_FILE = "relation_map.json"
MAX_NODES = 20


def _text(value: Any, limit: int = 0) -> str:
    s = " ".join(str(value or "").split())
    return s[:limit] if limit and len(s) > limit else s


def _characters(bible: dict[str, Any], relations: list[dict[str, Any]]) -> list[str]:
    """只收有关系的人：关系图里放一个连边都没有的节点只会占地方。

    没有人物卡的端点也补进来（否则边会缺一头）；排序按关系条数，人物卡顺序兜底。
    """
    degree: dict[str, int] = {}
    for r in relations:
        for name in (r.get("a"), r.get("b")):
            name = _text(name)
            if name:
                degree[name] = degree.get(name, 0) + 1
    cards = [_text(c.get("name")) for c in (bible.get("characters") or []) if isinstance(c, dict)]
    cards = [n for n in cards if n]
    order = {name: i for i, name in enumerate(cards)}
    names = [n for n in dict.fromkeys([*cards, *degree]) if degree.get(n)]
    names.sort(key=lambda n: (-degree.get(n, 0), order.get(n, len(order))))
    return names[:MAX_NODES]


def _character_line(bible: dict[str, Any], name: str) -> str:
    char = next(
        (c for c in (bible.get("characters") or [])
         if isinstance(c, dict) and _text(c.get("name")) == name),
        {},
    )
    bits = [name]
    for key, label in (("rolePosition", "身份"), ("importance", "重要度"), ("status", "状态"),
                       ("want", "想要"), ("fear", "怕"), ("currentGoal", "当前目标")):
        value = _text(char.get(key), 60)
        if value:
            bits.append(f"{label}:{value}")
    return "｜".join(bits)


def _messages(
    project: dict[str, Any],
    bible: dict[str, Any],
    relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    names = _characters(bible, relations)
    keep = set(names)
    edges = [
        r for r in relations
        if _text(r.get("a")) in keep and _text(r.get("b")) in keep
    ]
    factions = [
        f"- {_text(f.get('name'), 30)}"
        + (f"：{_text(f.get('nature') or f.get('text'), 80)}" if _text(f.get("nature") or f.get("text")) else "")
        for f in (bible.get("factions") or []) if isinstance(f, dict) and _text(f.get("name"))
    ]
    system = "\n".join([
        "你是中文网文的人物关系图绘制师。把这本书的人物和关系排成一张二维示意图，只输出一段独立 SVG。",
        "",
        "硬性要求：",
        "1. 只输出一个完整的 <svg>…</svg>：不要 Markdown 代码块，不要解释，不要 <html>/<body>。",
        '2. 根元素只写 viewBox="0 0 1000 720" xmlns="http://www.w3.org/2000/svg"；不要写 width/height，显示大小交给页面。',
        "2a. 不要分析、不要列提纲，读完数据直接从 <svg> 开始画。",
        "3. 自包含：不引用外部图片、字体、CSS、脚本；不要 <script>、<foreignObject>、<image>、on* 事件、javascript: 链接。",
        "4. 每个人物一个节点，节点里写姓名；只画给定的人物和关系，不新增人名，不虚构关系。",
        "5. 主角或关系最多的人放中心，其余按阵营/身份分簇摆在四周；同一簇用同色，簇与簇之间留白。",
        "6. 每条关系画一条连线，线旁写当前关系（可用短标签）；文字不许互相压住，也不许压住节点、连线或边框。",
        "7. 关系不分方向：用普通实线即可，不要画箭头；关系紧张用强调色，亲近用柔色，颜色只作区分不表达好坏。",
        "8. 标题只写一行，放在 y=40 附近；y<78 这条带只给标题。图例放左下或右下，写清颜色代表什么。",
        '9. 只用 <text> 写中文，font-family="Songti SC, Noto Serif SC, serif"；字号≥13。',
        "10. 配色像手绘设定稿：纸底 #f7f2e7，墨线 #2f2a24，辅助 #8a8072，强调 #b4543f / #3f6d7a / #8a6a2f / #4b6b45。",
        "11. 图要短：控制在 150 行以内，不写长注释、不重复样式。",
        "12. 底部 y>680 只留给图例，节点和关系标签不要落到这条带里。",
        "13. 关系超过 16 条时只画最主要的 16 条，优先画主角相关和当前状态最重要的。",
    ])
    user = "\n".join([
        f"书名：{_text(project.get('title'), 60)}｜题材：{_text(project.get('genre'), 40)}",
        "",
        "<人物>",
        "\n".join(_character_line(bible, n) for n in names),
        "</人物>",
        "",
        "<关系>",
        "\n".join(
            f"- {_text(r.get('a'), 30)} ↔ {_text(r.get('b'), 30)}："
            f"{_text(r.get('state'), 90)}"
            + (f"（{_text(r.get('note'), 80)}）" if _text(r.get("note")) else "")
            for r in edges
        ),
        "</关系>",
        "",
        "<世界>",
        _text(project.get("worldText"), 900) or "（无）",
        "</世界>",
        "",
        "<势力>",
        "\n".join(factions) or "（无）",
        "</势力>",
        "",
        "请输出 SVG。",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def load_relation_map(root: str | Any) -> dict[str, Any]:
    try:
        data = read_json(project_path(root, RELATION_MAP_FILE))
    except (FileNotFoundError, ValueError):
        return {"svg": "", "at": "", "model": ""}
    if not isinstance(data, dict):
        return {"svg": "", "at": "", "model": ""}
    svg = str(data.get("svg") or "")
    if not svg.lstrip().lower().startswith("<svg"):
        svg = ""
    else:
        svg = normalize_svg(svg)
    return {"svg": svg, "at": str(data.get("at") or ""), "model": str(data.get("model") or "")}


def generate_relation_map(root: str | Any, model: str | None = None) -> dict[str, Any]:
    project = load_project(root) or {}
    bible = load_bible(root)
    relations = effective_relations(root, bible)
    if len(_characters(bible, relations)) < 2 or not relations:
        raise ValueError("人物关系太少：先在设定页生成人物关系，再来画关系图")
    # 这类模型会先长考再画；16000 常被思考吃掉，SVG 还没开始就断了。
    svg, out = draw_svg(_messages(project, bible, relations), model=model, max_tokens=40000)
    doc = {
        "svg": svg,
        "at": now_iso(),
        "model": str(out.get("model") or ""),
    }
    with project_lock(root):
        write_json(project_path(root, RELATION_MAP_FILE), doc)
    return doc
