"""章节关系图谱：把「哪一章牵着哪一章」整理成节点 + 边。

数据全部来自已有的账本，不额外让模型生成、也不写新文件：

- 节点：``chapters/index.json`` 的每一章（字数、判定、卷、出场人物、摘要）；
- 伏笔边：``ledger/foreshadow.jsonl`` 的埋线章 → 收线章（未收的指向预计章，虚线）；
- 同场边：两章出场人物至少重合两人、且相隔不超过 10 章——读者能感到「同一批人
  又凑到一起了」，这是章节之间最实在的联系；
- 卷：节点上的 ``volume`` 字段，前端按卷分段上色。

图谱只读，不改任何账本。
"""

from __future__ import annotations

import os
from typing import Any

from ..store import project_path, read_index, read_jsonl
from ..store.jsonl import fold_foreshadow
from .memory import load_memory_rows, load_volumes

FORESHADOW_FILE = "ledger/foreshadow.jsonl"

#: 同场边最多跨多少章。再远就不是「同一场戏的余波」，而是另一条线了。
CAST_WINDOW = 10
#: 一章最多向外连几条同场边，避免高出场配角把图连成一团毛线。
CAST_LINKS_PER_NODE = 3


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _short(value: Any, limit: int) -> str:
    s = _text(value)
    return s[:limit] + "…" if len(s) > limit else s


def build_chapter_graph(root: str | os.PathLike) -> dict[str, Any]:
    index = read_index(root)
    if not index:
        return {
            "nodes": [],
            "edges": [],
            "volumes": [],
            "stats": {"chapters": 0, "edges": 0, "openForeshadows": 0, "paidForeshadows": 0},
        }

    memory = load_memory_rows(root)
    by_chapter = memory.get("byChapter") or {}
    raw_volumes = load_volumes(root)
    volumes = [
        {"volume": i + 1, "title": _text(v.get("title")),
         "from": _num(v.get("from")), "to": _num(v.get("to"))}
        for i, v in enumerate(raw_volumes)
        if _num(v.get("to"))
    ]

    foreshadows = [
        r for r in fold_foreshadow(read_jsonl(project_path(root, FORESHADOW_FILE)))
        if _text(r.get("name")) or _num(r.get("plantedChapter"))
    ]
    planted: dict[int, int] = {}
    paid: dict[int, int] = {}
    for f in foreshadows:
        p = _num(f.get("plantedChapter"))
        if p:
            planted[p] = planted.get(p, 0) + 1
        q = _num(f.get("payoffChapter"))
        if q:
            paid[q] = paid.get(q, 0) + 1

    nodes: list[dict[str, Any]] = []
    casts: dict[int, list[str]] = {}
    for row in index:
        n = _num(row.get("number"))
        if n <= 0:
            continue
        mem = by_chapter.get(n) or {}
        cast = [c for c in (mem.get("characters") or []) if _text(c)]
        casts[n] = cast
        vol = next((v for v in volumes if v["from"] <= n <= v["to"]), None)
        nodes.append({
            "id": f"c{n}",
            "number": n,
            "title": _text(row.get("title")) or f"第{n}章",
            "chars": _num(row.get("chars")),
            "verdict": _text(row.get("verdict")),
            "approved": bool(row.get("approved")),
            "hook": row.get("endHook") if isinstance(row.get("endHook"), dict) else None,
            "volume": _num((vol or {}).get("volume")),
            "volumeTitle": _text((vol or {}).get("title")),
            "cast": cast[:12],
            "summary": _short(mem.get("summary") or row.get("summary"), 110),
            "planted": planted.get(n, 0),
            "paid": paid.get(n, 0),
        })

    numbers = [n["number"] for n in nodes]
    edges: list[dict[str, Any]] = []

    # 1) 伏笔线：埋 → 收（未收的指向预计章，前端画虚线）。
    for f in foreshadows:
        p = _num(f.get("plantedChapter"))
        if p not in numbers:
            continue
        status = _text(f.get("status")) or "open"
        q = _num(f.get("payoffChapter")) or _num(f.get("dueChapter"))
        if status == "abandoned":
            continue
        if q and q in numbers and q != p:
            edges.append({
                "id": f"fs-{p}-{q}-{_text(f.get('id')) or _text(f.get('name'))}",
                "from": p,
                "to": q,
                "kind": "foreshadow",
                "label": _short(f.get("name"), 18),
                "status": "paid" if status == "paid" else "open",
                "due": _num(f.get("dueChapter")),
            })
        elif q and q not in numbers and status != "paid":
            edges.append({
                "id": f"fs-{p}-due-{_text(f.get('id')) or _text(f.get('name'))}",
                "from": p,
                "to": q,
                "kind": "foreshadow",
                "label": _short(f.get("name"), 18),
                "status": "planned",
                "due": q,
            })

    # 2) 同场边：人物重合至少两人，且相隔不超过 CAST_WINDOW 章。
    links: dict[int, int] = {n: 0 for n in numbers}
    for i, a in enumerate(numbers):
        ca = set(casts.get(a) or [])
        if len(ca) < 2:
            continue
        for b in numbers[i + 1:]:
            if b - a > CAST_WINDOW:
                break
            shared = ca & set(casts.get(b) or [])
            if len(shared) < 2:
                continue
            if links[a] >= CAST_LINKS_PER_NODE and links[b] >= CAST_LINKS_PER_NODE:
                continue
            names = [c for c in (casts.get(a) or []) if c in shared]
            edges.append({
                "id": f"cast-{a}-{b}",
                "from": a,
                "to": b,
                "kind": "cast",
                "label": "、".join(_short(x, 8) for x in names[:3]),
                "status": "",
            })
            links[a] += 1
            links[b] += 1

    stats = {
        "chapters": len(nodes),
        "edges": len(edges),
        "foreshadowEdges": sum(1 for e in edges if e["kind"] == "foreshadow"),
        "castEdges": sum(1 for e in edges if e["kind"] == "cast"),
        "openForeshadows": sum(1 for f in foreshadows if (_text(f.get("status")) or "open") == "open"),
        "paidForeshadows": sum(1 for f in foreshadows if _text(f.get("status")) == "paid"),
        "castlessChapters": sum(1 for n in nodes if not n["cast"]),
    }
    return {
        "nodes": nodes,
        "edges": edges,
        "volumes": volumes,
        "stats": stats,
    }
