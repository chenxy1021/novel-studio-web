"""规则分类、人物位置轨迹、物品持有链，以及它们进参考资料包的方式。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain import continuity, create, references, settings_gen
from app.store import load_bible, save_bible


def _book(tmp_path: Path, **kw) -> Path:
    return Path(create.create_book(title=kw.pop("title", "连续测试"), **kw)["dir"])


def _seed(root: Path, bible: dict) -> None:
    save_bible(root, {**load_bible(root), **bible})


def test_rule_enforce_maps_legacy_level_and_aliases():
    assert continuity.rule_enforce({"enforce": "契约"}) == "契约"
    assert continuity.rule_enforce({"level": "铁律"}) == "铁律"
    assert continuity.rule_enforce({"level": "惯例"}) == "惯例"
    assert continuity.rule_enforce({"enforce": "可以违反，但付代价"}) == "契约"
    assert continuity.rule_enforce({"enforce": "门规"}) == "惯例"
    assert continuity.rule_enforce({"enforce": "其实是迷信"}) == "谣言"
    # 老数据什么分类都没有时按铁律处理（旧版全叫「硬规则」）。
    assert continuity.rule_enforce({"name": "旧规则"}) == "铁律"
    assert "铁律" in continuity.rule_line({"name": "渡船不能空返", "cost": "少一个活人"})
    assert "违反代价" in continuity.rule_line({"name": "x", "cost": "y"})


def test_apply_continuity_records_moves_and_dedupes(tmp_path):
    root = _book(tmp_path)
    _seed(root, {
        "characters": [
            {"name": "老周", "location": "旧码头", "locationAt": 1},
            {"name": "阿雾", "aliases": ["雾姐"]},
        ],
        "items": [{"name": "断桨", "holder": "老周", "state": "裂了"}],
        "factions": [{"name": "船行会", "state": "按兵不动"}],
        "locations": [{"name": "旧码头", "state": "冷清", "occupied": ""}],
    })

    out = continuity.apply_continuity(
        root, 3,
        moves=[
            {"who": "雾姐", "to": "旧码头", "note": "搭渡船过河"},
            {"who": "老周", "to": "旧码头"},  # 没动
            {"who": "不存在的人", "to": "别处"},
        ],
        item_changes=[
            {"name": "断桨", "holder": "阿雾", "state": "断成两截", "note": "递给阿雾"},
        ],
        faction_changes=[
            {"name": "船行会", "state": "开始盯渡口", "note": "听说空船载了人"},
        ],
        place_changes=[
            {"name": "旧码头", "state": "被船行会盯着", "occupied": "船行会"},
        ],
    )
    assert out == {"moves": 1, "items": 2, "factions": 1, "places": 1}

    bible = load_bible(root)
    a = next(c for c in bible["characters"] if c["name"] == "阿雾")
    assert a["location"] == "旧码头"
    assert a["locationAt"] == 3
    assert a["locationHistory"] == [{"chapter": 3, "place": "旧码头", "note": "搭渡船过河"}]

    item = next(i for i in bible["items"] if i["name"] == "断桨")
    assert item["holder"] == "阿雾"
    assert item["holderAt"] == 3
    assert item["state"] == "断成两截"
    assert item["transferLog"][0]["from"] == "老周"
    assert item["transferLog"][0]["to"] == "阿雾"

    faction = next(f for f in bible["factions"] if f["name"] == "船行会")
    assert faction["state"] == "开始盯渡口"
    assert faction["stateAt"] == 3
    place = next(l for l in bible["locations"] if l["name"] == "旧码头")
    assert place["state"] == "被船行会盯着"
    assert place["stateAt"] == 3
    assert place["occupied"] == "船行会"

    # 同一章同一地点/同一持有人再写一次，不重复记账。
    again = continuity.apply_continuity(
        root, 3,
        moves=[{"who": "阿雾", "to": "旧码头"}],
        item_changes=[{"name": "断桨", "holder": "阿雾"}],
    )
    assert again["moves"] == 0
    bible = load_bible(root)
    a = next(c for c in bible["characters"] if c["name"] == "阿雾")
    assert len(a["locationHistory"]) == 1


def test_continuity_state_text_uses_as_of_chapter():
    text = continuity.continuity_state_text({
        "characters": [{
            "name": "老周", "location": "渡口", "locationAt": 4,
            "locationHistory": [{"chapter": 1, "place": "旧码头"}, {"chapter": 4, "place": "渡口"}],
        }],
        "items": [{"name": "断桨", "holder": "老周", "holderAt": 4, "state": "裂了"}],
    }, chapter=5)
    assert "截至第4章" in text
    assert "旧码头(第1章) → 渡口(第4章)" in text
    assert "持有者：老周" in text


def test_character_and_item_lines_carry_required_fields():
    line = continuity.character_line({
        "name": "阿雾", "rolePosition": "女主", "importance": "核心", "gender": "女",
        "age": "十六", "race": "人类", "personality": "先记下来再问", "status": "missing",
        "firstChapter": 2, "location": "旧码头", "locationAt": 3,
    })
    for bit in ("重要度:核心", "性别", "女", "年龄", "十六", "种族", "人类", "性格", "首次登场:第2章", "位置:旧码头", "截至第3章", "状态:失踪"):
        assert bit in line, bit

    item = continuity.item_line({
        "name": "断桨", "holder": "老周", "holderAt": 3, "state": "裂了",
        "transferLog": [{"chapter": 2, "from": "船行会", "to": "老周"}],
    })
    assert "持有:老周" in item and "截至第3章" in item and "状态:裂了" in item


def test_reference_pack_has_rules_and_info_gap_sections(tmp_path):
    root = _book(tmp_path)
    _seed(root, {
        "characters": [{
            "name": "老周", "location": "旧码头", "locationAt": 2,
            "locationHistory": [{"chapter": 1, "place": "渡口"}, {"chapter": 2, "place": "旧码头"}],
        }],
        "items": [{"name": "断桨", "holder": "老周", "holderAt": 2,
                   "transferLog": [{"chapter": 2, "from": "船行会", "to": "老周"}]}],
        "rules": [{"name": "渡船不能空返", "enforce": "契约", "cost": "少一个活人"}],
        "infoGaps": [{"secret": "阿雾早已死在河上", "knows": "阿雾", "doesntKnow": "老周"}],
    })
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["outlineText"] = "### 第1卷 起（第1-10章）\n老周与阿雾。"
    project["worldText"] = "雾港没有对岸。"
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    pack = references.build_reference_pack(root, 2)
    sec = {s["key"]: s for s in pack["sections"]}
    assert sec["rules"]["label"] == "规则"
    assert "[契约]" in sec["rules"]["text"]
    assert "信息差" == sec["info-gaps"]["label"]
    assert "阿雾早已死在河上" in sec["info-gaps"]["text"]
    assert "位置:旧码头" in sec["characters"]["text"]
    # continuity-state 只给卡片里没有的轨迹/转手，不再重复「当前位置」。
    assert "渡口(第1章) → 旧码头(第2章)" in sec["continuity-state"]["text"]
    assert "第2章从船行会到老周" in sec["continuity-state"]["text"]
    block = references.render_reference_block(pack)
    assert "【规则】" in block and "【信息差】" in block


def test_supplement_fills_empty_fields_without_overwriting(tmp_path, monkeypatch):
    root = _book(tmp_path)
    _seed(root, {"characters": [{"name": "老周", "want": "守住渡口"}]})
    chapters = root / "chapters"
    (chapters / "001-夜航.md").write_text("老周把船靠上旧码头。" * 30, encoding="utf-8")
    (chapters / "index.json").write_text(json.dumps([
        {"number": 1, "title": "夜航", "file": "chapters/001-夜航.md", "chars": 300, "summary": "老周夜航"},
    ], ensure_ascii=False), encoding="utf-8")

    def fake_chat(messages, **kwargs):
        return {"text": json.dumps({
            "characters": [{
                "name": "老周", "want": "改成别的", "location": "旧码头",
                "status": "active", "gender": "男", "personality": "认死理",
            }],
        }, ensure_ascii=False), "model": "fake", "usage": {}}

    monkeypatch.setattr(settings_gen, "chat", fake_chat)
    out = settings_gen.supplement_settings(root, recent=2)

    assert out["added"]["characters"] == 0
    assert out["filled"]["characters"] == 1
    c = load_bible(root)["characters"][0]
    assert c["want"] == "守住渡口"       # 不覆盖
    assert c["location"] == "旧码头"     # 补空字段
    assert c["gender"] == "男"
    assert "补" in out["summary"]
