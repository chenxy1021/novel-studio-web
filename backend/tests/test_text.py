"""人名 / 场景 / 地点判定与 JS 原版一致。

这些结果直接决定体检报什么问题（谁该登场没登场、上一章在哪收的），
差一个人名就是一条误报或漏报。
"""

from app.domain import text as T


def test_role_descriptor():
    assert [T.is_role_descriptor(n) for n in ["赵家长工", "会院守井老汉", "老韩", "同期新人·老韩", "镜"]] == [
        True, True, False, False, False,
    ]


def test_split_scenes_synthetic():
    assert T.split_scenes("第一段。\n\n第二段。\n\n次日他又来了。\n\n回到警局，桌上放着信。") == [
        {"i": 1, "text": "第一段。\n第二段。"},
        {"i": 2, "text": "次日他又来了。"},
        {"i": 3, "text": "回到警局，桌上放着信。"},
    ]
    assert T.split_scenes("只有一段很长的话，没有空行。" * 3) == [
        {"i": 1, "text": "只有一段很长的话，没有空行。" * 3},
    ]


def test_hard_rule_hits_only_uses_forbidden_keywords():
    rules = [
        {"name": "夜禁", "forbiddenKeywords": ["白天出门", "日出"], "trigger": "只在夜里"},
        {"name": "无禁用词", "trigger": "随便"},
    ]
    hits = T.hard_rule_hits(rules, "他白天出门，忘了日出前回来。")
    assert hits == [{"rule": "夜禁", "matched": "白天出门、日出"}]
    # trigger 不是禁用词：文本提到触发条件不算违规
    assert T.hard_rule_hits(rules, "他只在夜里行动。") == []
