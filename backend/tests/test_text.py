"""人名 / 场景 / 地点判定与 JS 原版一致。

这些结果直接决定体检报什么问题（谁该登场没登场、上一章在哪收的），
差一个人名就是一条误报或漏报。
"""

import json
from pathlib import Path

import pytest

from app.domain import text as T

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = json.loads((FIXTURES / "text_golden.json").read_text(encoding="utf-8"))


def test_chapters_match_js_golden(signal_tower, hunting_tower):
    for bj, root in zip(GOLDEN["books"], [signal_tower, hunting_tower]):
        bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in (bible.get("characters") or [])]
        index = json.loads((root / "chapters" / "index.json").read_text(encoding="utf-8"))
        index.sort(key=lambda c: c["number"])
        for jc, c in zip(bj["chapters"], index):
            body = (root / c["file"]).read_text(encoding="utf-8")
            assert T.split_scenes(body) == jc["scenes"], f"{root.name} ch{c['number']} scenes"
            assert T.spot_scenes(body, names[:2]) == jc["spots"], f"{root.name} ch{c['number']} spots"
            assert T.name_positions(body, names[:4], names) == jc["namePos"], f"{root.name} ch{c['number']} names"


def test_same_person_and_role(signal_tower, hunting_tower):
    for bj, root in zip(GOLDEN["books"], [signal_tower, hunting_tower]):
        bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in (bible.get("characters") or [])]
        assert [[T.same_person(a, b) for b in names[:5]] for a in names[:5]] == bj["same"]
    assert [T.is_role_descriptor(n) for n in ["赵家长工", "会院守井老汉", "老韩", "同期新人·老韩", "镜"]] == GOLDEN["books"][0]["role"]


def test_split_scenes_synthetic():
    assert T.split_scenes("第一段。\n\n第二段。\n\n次日他又来了。\n\n回到警局，桌上放着信。") == GOLDEN["syn"]
    assert T.split_scenes("只有一段很长的话，没有空行。" * 3) == GOLDEN["syn2"]


def test_hard_rule_hits_only_uses_forbidden_keywords():
    rules = [
        {"name": "夜禁", "forbiddenKeywords": ["白天出门", "日出"], "trigger": "只在夜里"},
        {"name": "无禁用词", "trigger": "随便"},
    ]
    hits = T.hard_rule_hits(rules, "他白天出门，忘了日出前回来。")
    assert hits == [{"rule": "夜禁", "matched": "白天出门、日出"}]
    # trigger 不是禁用词：文本提到触发条件不算违规
    assert T.hard_rule_hits(rules, "他只在夜里行动。") == []
