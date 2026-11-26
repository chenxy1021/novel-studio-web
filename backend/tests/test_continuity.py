"""规则分类、人物位置轨迹、物品持有链，以及它们进参考资料包的方式。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain import continuity, create, references, settings_gen
from app.store import load_bible, save_bible


def _book(tmp_path: Path, **kw) -> Path:
    title = kw.pop("title", "连续测试")
    books = tmp_path / "books"
    books.mkdir(exist_ok=True)
    old = create.books_root
    create.books_root = lambda: books
    try:
        return Path(create.create_book(title=title, **kw)["dir"])
    finally:
        create.books_root = old


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
    assert out == {"moves": 1, "items": 2, "factions": 1, "places": 1, "characters": 0, "debuts": 0}

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
                "status": "active", "finalStatus": "dead", "gender": "男", "personality": "认死理",
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
    assert c["finalStatus"] == "dead"    # 最终状态也靠补进设定填
    assert "补" in out["summary"]


# ------------------------- 人物状态：出场 / 当前 / 最终 ------------------------- #


def test_character_status_tracks_appearance_current_and_final():
    """出场活着、第 40 章死了：出场状态、当前状态、最终状态各是各的。"""
    c = {
        "name": "老周", "status": "dead", "statusAt": 40, "firstChapter": 2,
        "appearanceStatus": "active", "finalStatus": "dead",
        "statusLog": [{"chapter": 40, "status": "dead", "note": "替阿雾挡刀"}],
    }
    at = continuity.character_status_at(c)
    assert at["appearance"] == "active"
    assert at["current"] == "dead" and at["currentAt"] == 40
    assert at["final"] == "dead"

    # 写第 20 章时他还活着：那一章的死亡不提前生效。
    before = continuity.character_status_at(c, before_chapter=20)
    assert before["current"] == "active"
    assert continuity.character_status_at(c, before_chapter=41)["current"] == "dead"

    line = continuity.character_line(c)
    assert "状态:在场→死亡（第40章起）" in line
    assert "最终" not in line  # 当前已经是结局状态，就不再重复


def test_character_status_line_marks_planned_final_state():
    c = {"name": "阿雾", "status": "active", "firstChapter": 1, "finalStatus": "missing"}
    line = continuity.character_line(c)
    assert "状态:在场" in line
    assert "最终:失踪" in line


def test_apply_continuity_records_character_status_and_exit(tmp_path):
    root = _book(tmp_path)
    _seed(root, {"characters": [{"name": "老周", "status": "active", "firstChapter": 1}]})

    out = continuity.apply_continuity(
        root, 40, character_changes=[{"who": "老周", "status": "死亡", "note": "替阿雾挡刀"}],
    )
    assert out["characters"] == 1
    c = next(x for x in load_bible(root)["characters"] if x["name"] == "老周")
    assert c["statusLog"] == [{"chapter": 40, "status": "dead", "note": "替阿雾挡刀"}]
    assert c["exitChapter"] == 40
    assert c["status"] == "dead" and c["statusAt"] == 40  # 当前状态跟着推到死亡
    assert c["appearanceStatus"] == "active"             # 出场时是活的

    # 同一章重放（补进设定、重算都跑一遍）不重复记账，也不算新变化。
    again = continuity.apply_continuity(
        root, 40, character_changes=[{"who": "老周", "status": "死亡", "note": "替阿雾挡刀"}],
    )
    assert again["characters"] == 0

    # 和这一刻一样的状态不算变化：第 41 章他仍然是死的。
    noop = continuity.apply_continuity(
        root, 41, character_changes=[{"who": "老周", "status": "死亡"}],
    )
    assert noop["characters"] == 0


def test_undo_chapter_rolls_back_character_status(tmp_path):
    root = _book(tmp_path)
    _seed(root, {"characters": [{"name": "老周", "status": "active", "firstChapter": 1}]})
    continuity.apply_continuity(root, 12, character_changes=[{"who": "老周", "status": "失踪"}])
    continuity.apply_continuity(root, 40, character_changes=[{"who": "老周", "status": "死亡"}])

    counts = continuity.undo_chapter(root, 40)
    assert counts["characters"] == 1
    c = next(x for x in load_bible(root)["characters"] if x["name"] == "老周")
    assert [r["chapter"] for r in c["statusLog"]] == [12]
    assert c["status"] == "missing" and c["statusAt"] == 12  # 当前状态退回失踪
    assert c["exitChapter"] == 12  # 退场章退回还剩下的第一条

    continuity.undo_chapter(root, 12)
    c = next(x for x in load_bible(root)["characters"] if x["name"] == "老周")
    assert c["statusLog"] == []
    assert c["exitChapter"] == 0
    assert c["status"] == "active"  # 退回出场状态


def test_reapply_chapter_folds_character_states_from_memory(tmp_path):
    """存档回写时，章记忆里的出场名单和 characterStates 一起并进设定。

    出场：第一次出现在正文里的人补 firstChapter + appearanceStatus；
    当前/退场：characterStates 并进 statusLog / statusAt / exitChapter。
    """
    from app.domain.memory import append_memory

    root = _book(tmp_path)
    _seed(root, {"characters": [
        {"name": "老周", "status": "active", "firstChapter": 1},
        {"name": "阿雾", "status": "active"},
    ]})
    chapters = root / "chapters"
    (chapters / "007-夜航.md").write_text("老周夜航，没回来。" * 30, encoding="utf-8")
    (chapters / "index.json").write_text(json.dumps([
        {"number": 7, "title": "夜航", "file": "chapters/007-夜航.md", "chars": 300, "summary": "老周失踪"},
    ], ensure_ascii=False), encoding="utf-8")
    append_memory(root, {
        "kind": "chapter", "chapter": 7, "summary": "老周失踪。",
        "characters": ["老周", "阿雾"],
        "characterStates": [{"who": "老周", "status": "失踪", "note": "夜航后没回来"}],
    })
    counts = continuity.reapply_chapter(root, 7)
    assert counts["characters"] == 1
    assert counts["debuts"] == 1
    c = next(x for x in load_bible(root)["characters"] if x["name"] == "老周")
    assert c["statusLog"] == [{"chapter": 7, "status": "missing", "note": "夜航后没回来"}]
    assert c["status"] == "missing" and c["appearanceStatus"] == "active"
    assert c["exitChapter"] == 7
    mist = next(x for x in load_bible(root)["characters"] if x["name"] == "阿雾")
    assert mist["firstChapter"] == 7 and mist["appearanceStatus"] == "active"

    # 同一章重放不重复记（已有 firstChapter 和状态轨迹）。
    again = continuity.reapply_chapter(root, 7)
    assert again["debuts"] == 0 and again["characters"] == 0

    # 退稿：这一章的首次登场和状态变化一起撤回。
    continuity.undo_chapter(root, 7)
    after = load_bible(root)["characters"]
    mist = next(x for x in after if x["name"] == "阿雾")
    assert mist["firstChapter"] == 0 and mist["appearanceStatus"] == ""
    c = next(x for x in after if x["name"] == "老周")
    assert c["statusLog"] == [] and c["status"] == "active"


def _dead_zhow() -> dict:
    return {"characters": [{
        "name": "老周", "status": "dead", "statusAt": 40, "firstChapter": 2,
        "statusLog": [{"chapter": 40, "status": "dead", "note": "替阿雾挡刀"}],
    }]}


def test_chapter_conflicts_flags_gone_character_written_as_active():
    """第 40 章死了，第 41 章的记忆又把他记成在场：这是写后忘前最硬的一种。"""
    row = {"chapter": 41, "characterStates": [{"who": "老周", "status": "在场"}]}
    out = continuity.chapter_conflicts(_dead_zhow(), 41, row)
    assert [x["code"] for x in out] == ["gone-character-active"]
    assert out[0]["severity"] == "high"
    assert "第40章已经死亡" in out[0]["message"]
    assert out[0]["who"] == "老周"


def test_chapter_conflicts_respects_flashback_and_excuses():
    """回忆章不算；备注里写明是回忆/尸体/传闻的也不算。"""
    row = {"chapter": 41, "characterStates": [{"who": "老周", "status": "在场"}]}
    assert continuity.chapter_conflicts(_dead_zhow(), 41, {**row, "isFlashback": True}) == []

    for note in ("回忆里的老周", "只是尸体被人抬进来", "诈死，其实没死", "船行会的传闻"):
        excused = {"chapter": 41, "characterStates": [{"who": "老周", "status": "在场", "note": note}]}
        assert continuity.chapter_conflicts(_dead_zhow(), 41, excused) == [], note

    # 正文那句整体交代成回忆，也算说明。
    state = {"chapter": 41, "state": "全章是阿雾的回忆", "characterStates": [{"who": "老周", "status": "在场"}]}
    assert continuity.chapter_conflicts(_dead_zhow(), 41, state) == []

    # 本章才死的，反而是正常推进，不报。
    fresh = {"chapter": 40, "characterStates": [{"who": "老周", "status": "死亡"}]}
    assert continuity.chapter_conflicts(_dead_zhow(), 40, fresh) == []


def test_chapter_conflicts_flags_moves_by_gone_character():
    row = {"chapter": 41, "moves": [{"who": "老周", "to": "旧码头", "note": "又回来了"}]}
    out = continuity.chapter_conflicts(_dead_zhow(), 41, row)
    assert [x["code"] for x in out] == ["gone-character-move"]
    assert out[0]["severity"] == "mid"


def test_chapter_conflicts_ignores_planned_death_from_outline():
    """设定里写着「第 55 章死」但还没有按章轨迹：前面各章不能当他一直死。"""
    planned = {"characters": [{
        "name": "赵婶", "status": "dead", "exitChapter": 55, "firstChapter": 6,
    }]}
    row = {"chapter": 30, "moves": [{"who": "赵婶", "to": "配给站"}],
           "characterStates": [{"who": "赵婶", "status": "在场"}]}
    assert continuity.chapter_conflicts(planned, 30, row) == []
    # 真到第 55 章，死亡才生效——那也不是「已经死」，本章照常。
    assert continuity.chapter_conflicts(planned, 55, row) == []
    assert continuity.chapter_conflicts(planned, 56, row)  # 之后才算数


def test_gone_at_separates_planned_death_from_real_one():
    planned = {"name": "韩序", "status": "dead", "exitChapter": 76, "firstChapter": 1}
    assert continuity.gone_at(planned, 56) is None       # 计划在后面的死不算
    assert continuity.gone_at(planned, 76) is None       # 死在当章，本章还在
    assert continuity.gone_at(planned, 77) == ("dead", 76)

    logged = {"name": "赵婶", "status": "dead", "firstChapter": 6,
              "statusLog": [{"chapter": 55, "status": "dead", "note": "自焚"}]}
    assert continuity.gone_at(logged, 55) is None
    assert continuity.gone_at(logged, 56) == ("dead", 55)

    unmarked = {"name": "老登记员", "status": "dead", "firstChapter": 31}
    assert continuity.gone_at(unmarked, 56) == ("dead", 0)  # 不知道哪章，但不编章号
    alive = {"name": "老秦", "status": "active"}
    assert continuity.gone_at(alive, 56) is None

    later = {"name": "王叔", "status": "missing", "firstChapter": 63}
    assert continuity.gone_at(later, 56) is None         # 本章还没登场
    assert continuity.gone_at(later, 63) == ("missing", 0)  # 当章登场，按已离场但无章号


def test_character_line_writes_status_as_of_the_chapter():
    """写第 56 章时，第 76 章才死的韩序是「在场」，不能写成「死亡」。"""
    c = {"name": "韩序", "status": "dead", "exitChapter": 76, "firstChapter": 1}
    assert "状态:死亡" in continuity.character_line(c)             # 默认仍是当前状态
    line = continuity.character_line(c, chapter=56)
    assert "状态:在场（第76章起死亡）" in line
    assert continuity.character_line(c, chapter=80).startswith("【人物·韩序】")
    assert "状态:死亡" in continuity.character_line(c, chapter=80)


def test_character_line_separates_current_status_from_planned_exit():
    """按章记录的标准写法：status 是已写到的当前状态，finalStatus 才是结局。

    第 65 章时的韩序仍在场；退场第 76 章只是计划，不能把退场章当成本章
    状态变化的起点（曾渲染成「在场（第76章起在场）」）。
    """
    c = {"name": "韩序", "status": "active", "finalStatus": "dead",
         "appearanceStatus": "active", "firstChapter": 1, "exitChapter": 76}
    line = continuity.character_line(c, chapter=56)
    assert "状态:在场" in line
    assert "第76章起在场" not in line
    assert "最终:死亡" in line
    assert "退场:第76章（计划）" in line
    assert continuity.gone_at(c, 56) is None
    # 退场章过后，当前状态与结局一致，不再重复写「最终」
    later = continuity.character_line(c, chapter=80)
    assert "状态:在场" in later  # 数据还没回写 76 章的变化
    assert "退场:第76章" in later and "（计划）" not in later
