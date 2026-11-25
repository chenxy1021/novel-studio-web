"""人物关系图提示词与落盘：全部离线，不调模型。"""

from __future__ import annotations

from app.domain import relation_gen


def test_prompt_uses_characters_relations_and_factions() -> None:
    project = {"title": "雾港纪事", "genre": "悬疑", "worldText": "雾港分东西两岸，渡口由船行会把持。"}
    bible = {
        "characters": [
            {"name": "老周", "rolePosition": "主角", "want": "守住渡口"},
            {"name": "阿雾", "rolePosition": "女主", "fear": "被忘记"},
        ],
        "factions": [{"name": "船行会", "nature": "控制所有渡船"}],
    }
    relations = [
        {"a": "老周", "b": "阿雾", "state": "互相试探", "note": "第2章开始信任"},
    ]
    system, user = [m["content"] for m in relation_gen._messages(project, bible, relations)]
    assert "只输出一个完整的 <svg>" in system
    assert "老周" in user and "阿雾" in user
    assert "互相试探" in user
    assert "船行会" in user
    assert "雾港分东西两岸" in user


def test_characters_skip_cards_without_relations() -> None:
    """没有关系的人物卡不画进关系图；关系里出现、卡里没有的人也补进来。"""
    bible = {
        "characters": [
            {"name": "老周"},
            {"name": "阿雾"},
            {"name": "卫石头"},
        ],
    }
    relations = [
        {"a": "老周", "b": "阿雾", "state": "互相试探"},
        {"a": "老周", "b": "船行会", "state": "被追债"},
    ]
    names = relation_gen._characters(bible, relations)
    assert names == ["老周", "阿雾", "船行会"]
    assert "卫石头" not in names


def test_load_relation_map_defaults_when_missing(tmp_path) -> None:
    assert relation_gen.load_relation_map(tmp_path) == {"svg": "", "at": "", "model": ""}
