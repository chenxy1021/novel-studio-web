"""记忆层移植验收：章记忆 / 卷记忆 / 人物状态 / 关系 / 回查 / 技能路由 / 预算分配
全部与 JS 原版逐字段一致（golden 由 scripts/gen_memory_golden.mjs 用原版跑出来）。

这些文本会直接拼进给模型的提示词，差一个字就是给模型不同的指令。
"""

import json
from pathlib import Path

import pytest

from app.domain import memory

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = json.loads((FIXTURES / "memory_golden.json").read_text(encoding="utf-8"))


@pytest.fixture
def gold(signal_tower, hunting_tower):
    """golden 按 [信号塔, 猎场] 的顺序生成。"""
    return GOLDEN, [signal_tower, hunting_tower]


def _names(root: Path) -> list[str]:
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    return [c["name"] for c in (bible.get("characters") or [])]


def test_books_match_js_golden(gold):
    G, roots = gold
    for bj, root in zip(G["books"], roots):
        proj = json.loads((root / "project.json").read_text(encoding="utf-8"))
        bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
        names = _names(root)
        got = {
            "parseVolumes": memory.parse_volumes(proj.get("outlineText") or ""),
            "volumes": memory.load_volumes(root),
            "echo6": memory.build_echo_memory(root, chapter=6),
            "echo9": memory.build_echo_memory(root, chapter=9),
            "echo12": memory.build_echo_memory(root, chapter=12),
            "echoBig": memory.build_echo_memory(root, chapter=40, budget_chars=4000),
            "echoFocus": memory.build_echo_memory(root, chapter=9, focus=names[:2]),
            "vol6": memory.volume_memory(root, chapter=6),
            "volLatest": memory.volume_memory(root, chapter=9),
            "state6": memory.character_state(root, chapter=6, names=names[:3]),
            "relations": memory.load_relations(root),
            "relLines": memory.relation_lines(root, names[:3]),
            "recall": memory.recall_memory(root, query=names[0] if names else "塔", limit=5),
            "recallMiss": memory.recall_memory(root, query="不存在的关键词xyz"),
            "aliases": [memory.aliases_of(c) for c in (bible.get("characters") or [])],
            "resolve": [
                (memory.resolve_character(bible, c["name"]) or {}).get("name")
                for c in (bible.get("characters") or [])
            ],
        }
        for key in got:
            assert got[key] == bj[key], f"{root.name}.{key}"


def test_pure_helpers_match_js(gold):
    G, _ = gold
    pure = G["pure"]
    assert [memory.cn_num(s) for s in ["一", "十", "十二", "二十三", "一百二十", "第", "", "36", "百"]] == pure["cnNum"]
    assert [
        memory.clamp_summary("一二三四五六七八九十一二三四五", 6),
        memory.clamp_summary("说了很久很久的话。然后又说了很多。再然后就没有然后了。这句话很长很长很长", 20),
        memory.clamp_summary("第一行\n\n第二行   第三行"),
        memory.clamp_summary("", 10),
    ] == pure["clamp"]
    assert [memory.pack_budget(n) for n in [0, 100, 4000, 5000, 8000, 12000, 20000]] == pure["pack"]


@pytest.mark.parametrize("key,text", [
    ("parseV1", "## 第一卷 风起\n- 第 1-36 章\n## 第二卷 雨落\n- 第 37-80 章"),
    ("parseV2", "- **第一卷 第 1-36 章｜第一单**\n- **第二卷 第 37-72 章｜第二单**"),
    ("parseV3", "## 全书层\n- 第 1-500 章\n## 第 1-120 章 发现线索\n## 第 121-300 章 真相"),
    ("parseV4", "## 第一部 旧卷疑云\n### 第一卷 第 1-30 章 任务：查案\n### 第二卷 第 31-60 章 任务：收网"),
    ("parseV5", "## 第一部 旧卷疑云\n### 第一卷 第 1-30 章\n# 第 3卷 轮回之证 第31-50章"),
    ("parseV6", ""),
])
def test_parse_volumes_match_js(gold, key, text):
    G, _ = gold
    assert memory.parse_volumes(text) == G["pure"][key]


def test_skill_routes_match_js(gold):
    G, _ = gold
    for action in memory.SKILL_ROUTES:
        for opts in ({}, {"length": "short"}, {"length": "long"}, {"platform": "知乎"}, {"ref": True}, {"scope": "characters"}):
            key = action + json.dumps(opts, separators=(",", ":"), ensure_ascii=False)
            assert memory.skill_block(action, opts) == G["skills"][key], key


def test_fit_sections_match_js(gold):
    G, _ = gold
    sections = [
        {"key": "a", "title": "细纲", "text": "字" * 1000, "critical": True},
        {"key": "b", "title": "规则", "text": "字" * 3000, "critical": True},
        {"key": "c", "title": "人物", "text": "字" * 800, "critical": False, "weight": 2},
        {"key": "d", "title": "前情", "text": "字" * 6000, "critical": False, "weight": 1.5},
        {"key": "e", "title": "前情min", "text": "字" * 6000, "critical": False, "weight": 1.5,
         "max": float("inf"), "min": 1600},
        {"key": "f", "title": "大段", "text": "字" * 9000, "critical": False, "weight": 1, "max": 5000},
    ]
    assert memory.fit_sections(sections, 8000) == G["fit"]["a"]
    assert memory.fit_sections(sections[:2], 5000) == G["fit"]["b"]
    assert memory.fit_sections([{"key": "x", "title": "x", "text": "", "critical": False}], 8000) == G["fit"]["c"]
