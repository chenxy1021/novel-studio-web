"""开书流水线：梗概 → 大纲+世界观 → 设定 → 伏笔 → 细纲+正文。全部离线（monkeypatch chat）。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import blueprint, create, foreshadow_gen, settings_gen, writing
from app.main import app
from app.store import load_bible, load_project, save_project
from app.store.jsonl import append_jsonl, read_jsonl

client = TestClient(app)


def _book(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    data = {
        "title": "雾港纪事",
        "genre": "悬疑·民俗",
        "platform": "generic",
        "target_chapters": 30,
        "words_per_chapter": 1000,
        "logline": "渡船每夜多载一个不存在的人。",
        "synopsis": "摆渡人老周守着一座没有对岸的渡口，直到一个自称是他女儿的乘客上船。" * 3,
    }
    data.update(kwargs)
    info = create.create_book(**data)
    return Path(info["dir"])


def test_blueprint_splits_outline_and_world(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    seen: list[list[dict]] = []

    fake_text = "\n".join([
        "## 第一部分：全书大纲",
        "### 1. 全书层",
        "- 一句话故事核：老周想守住渡口，被一个自称女儿的乘客挡住。",
        "### 2. 卷层",
        "### 第1卷 无岸（第1-15章）",
        "- 任务与矛盾：老周要弄清乘客身份。",
        "- 卷内节拍：老周夜航 → 乘客留下湿脚印。",
        "### 第2卷 归渡（第16-30章）",
        "- 任务与矛盾：老周必须决定渡谁过河。",
        "## 第二部分：世界观",
        "### 1. 世界基底",
        "雾港没有对岸，渡船靠执念维持。",
        "### 5. 势力与恩怨",
        "船行会欠老周一条命。",
    ])

    def fake_chat(messages, **kwargs):
        seen.append(messages)
        return {"text": fake_text, "model": "m", "usage": {}}

    monkeypatch.setattr(blueprint, "chat", fake_chat)
    res = blueprint.generate_blueprint(root)

    assert res["outlineText"].startswith("### 1. 全书层")
    assert "世界基底" in res["worldText"]
    assert [v["title"] for v in res["volumes"]] == ["第1卷 无岸", "第2卷 归渡"]
    project = load_project(root)
    assert project["outlineText"] == res["outlineText"]
    assert project["worldText"] == res["worldText"]
    assert "下一步生成" in project["gate"]["reason"]


def test_blueprint_uses_nuewen_logic(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch, nuewen=True)
    seen: list[list[dict]] = []

    def fake_chat(messages, **kwargs):
        seen.append(messages)
        return {
            "text": "## 第一部分：全书大纲\n### 1. 全书层\n- 一句话故事核：老周想守住渡口，被一个自称女儿的乘客挡住。\n"
                    "- 主角的欲望、恐惧、致命缺陷：想弄清她是谁，怕对岸根本不存在，缺陷是不肯回头。\n"
                    "### 第1卷 起（第1-30章）\n- 任务与矛盾：老周要逐夜验证乘客的身份，船行会却要收走他的船。\n"
                    "## 第二部分：世界观\n### 1. 世界基底\n雾港没有对岸，渡船靠执念维持；船行会靠收记忆维持渡口。\n",
            "model": "m",
            "usage": {},
        }

    monkeypatch.setattr(blueprint, "chat", fake_chat)
    blueprint.generate_blueprint(root)
    system = seen[0][0]["content"]
    assert "最想活的死" in system
    assert "不预设结局形状" in system
    assert "结局不圆满" not in system


def test_generate_settings_merges_and_skips_duplicates(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    project = load_project(root)
    project["outlineText"] = "### 第1卷 起（第1-30章）\n老周与阿雾。"
    project["worldText"] = "## 1. 世界基底\n雾港没有对岸。"
    save_project(root, project)

    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        system = messages[0]["content"]
        calls.append(system)
        if "人物档案员" in system:
            return {
                "text": json.dumps({
                    "characters": [
                        {"name": "老周", "aliases": ["周叔", "老摆渡"], "rolePosition": "主角", "importance": "核心", "want": "守住渡口"},
                        {"name": "阿雾", "rolePosition": "女主", "importance": "核心", "secret": "她早已死在河上"},
                    ],
                    "relations": [{"a": "老周", "b": "阿雾", "state": "父女但彼此提防"}],
                    "infoGaps": [{"secret": "阿雾的身份", "knows": "阿雾", "doesntKnow": "老周"}],
                }, ensure_ascii=False),
                "model": "m", "usage": {},
            }
        return {
            "text": json.dumps({
                "world": [{"name": "雾港", "text": "没有对岸的渡口"}],
                "factions": [{
                    "name": "船行会", "hiddenRules": "过河要拿记忆换",
                    "state": "老周欠他们一条命，暂时不动他", "stateAt": 3, "attitude": "观望",
                }],
                "locations": [{
                    "name": "旧码头", "accessRules": "入夜后不接生客",
                    "state": "被船行会盯着", "stateAt": 3, "occupied": "船行会",
                }],
                "items": [{"name": "断桨", "holder": "老周"}],
                "rules": [{"name": "渡船不能空返", "text": "空船返航会多载一个人", "cost": "少一个活人"}],
                "powerSystem": {
                    "name": "摆渡阶",
                    "levels": [{"name": "引路人"}, {"name": "守渡人", "gap": "守渡人能看见空船上的客"}],
                },
                "society": {"currency": "冥钞", "taboo": "夜里不喊乘客的名字"},
                "history": [{"era": "旧朝", "year": "三十年前", "event": "断桥之战", "impact": "两岸断了往来"}],
                "glossary": [{"term": "空返", "meaning": "船不载客回程", "usage": "老周忌讳说这两个字"}],
                "style": {"pov": "第三人称限知", "samples": ["模型编的示范文，不该入库"]},
            }, ensure_ascii=False),
            "model": "m", "usage": {},
        }

    monkeypatch.setattr(settings_gen, "chat", fake_chat)
    res = settings_gen.generate_settings(root)

    assert res["added"]["characters"] == 2
    assert res["added"]["rules"] == 1
    bible = load_bible(root)
    assert [c["name"] for c in bible["characters"]] == ["老周", "阿雾"]
    assert bible["characters"][0]["aliases"] == ["周叔", "老摆渡"]
    assert bible["factions"][0]["stateAt"] == 3
    assert bible["factions"][0]["attitude"] == "观望"
    assert bible["locations"][0]["state"] == "被船行会盯着"
    assert bible["locations"][0]["occupied"] == "船行会"
    assert bible["relations"][0]["a"] == "老周"
    assert bible["infoGaps"][0]["secret"] == "阿雾的身份"
    assert bible["style"]["pov"] == "第三人称限知"
    # 样章只来自己选定的作家预设 / 手填，拆设定不写 samples。
    assert not bible["style"].get("samples")
    assert [x["name"] for x in bible["powerSystem"]["levels"]] == ["引路人", "守渡人"]
    assert bible["society"]["currency"] == "冥钞"
    assert bible["history"][0]["event"] == "断桥之战"
    assert bible["glossary"][0]["term"] == "空返"
    assert len(calls) == 4  # 人物 1 次 + 设定 3 批（空间 / 规则与物品 / 世界纵深）

    # 再跑一次：同名全部跳过，不重复入库
    res2 = settings_gen.generate_settings(root)
    assert res2["added"]["characters"] == 0
    assert res2["added"]["history"] == 0
    assert len(load_bible(root)["characters"]) == 2
    assert len(load_bible(root)["powerSystem"]["levels"]) == 2
    assert len(load_bible(root)["glossary"]) == 1


def test_generate_foreshadows_writes_ledger_and_guards_gap(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    project = load_project(root)
    project["outlineText"] = "### 第1卷 起（第1-30章）\n老周与阿雾。"
    project["worldText"] = "## 1. 世界基底\n雾港没有对岸。"
    save_project(root, project)

    lines = "\n".join([
        "名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃",
        "断桨|主线|物品·断桨|1|拍2 老周握桨的手在抖|3|阿雾|证明老周早就知道|反复摸桨柄|改由船票编号替代",
        "湿脚印|卷内|硬规则·渡船不能空返|2|拍1 甲板上一串水印|4|老周|说明空船真的载过人|脚印每晚多一个|让水印消失",
        "旧船票|细节|地点·旧码头|2|拍3 票根压在砖下|3|阿雾|票根日期对不上|阿雾捏票根|改成一张欠条",
    ])

    def fake_chat(messages, **kwargs):
        return {"text": lines, "model": "m", "usage": {}}

    monkeypatch.setattr(foreshadow_gen, "chat", fake_chat)
    res = foreshadow_gen.generate_foreshadows(root)

    assert res["count"] == 3
    assert res["guarded"] == 2  # 主线 1→3 推到 11，卷级 2→4 推到 7
    rows = [r for r in read_jsonl(root / "ledger/foreshadow.jsonl") if not r.get("__corrupt")]
    assert len(rows) == 3
    main = next(r for r in rows if r["name"] == "断桨")
    assert main["kind"] == "main"
    assert main["dueChapter"] == 11
    assert load_project(root)["foreshadowAt"]


def test_generate_chapter_writes_outline_and_prose(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    project = load_project(root)
    project["outlineText"] = "\n".join([
        "### 第1卷 无岸（第1-30章）",
        "- 任务与矛盾：老周要弄清乘客身份。",
    ])
    project["worldText"] = "## 1. 世界基底\n雾港没有对岸。"
    save_project(root, project)
    append_jsonl(root / "ledger/foreshadow.jsonl", {
        "id": "fs-test", "name": "断桨", "kind": "main", "plantedChapter": 1,
        "dueChapter": 5, "status": "open", "source": "测试", "at": "",
    })

    outline_json = {
        "chapter": 1,
        "title": "夜航",
        "beats": ["拍1：老周在码头收船 → 一个湿透的女人上船 → 她没有影子", "拍2：老周想赶她下船 → 她报出他女儿的名字 → 他握紧了断桨"],
        "mustInclude": ["断桨", "湿脚印"],
        "mustAvoid": ["不要解释渡口的来历"],
        "openingState": "雾港旧码头，入夜",
        "endingState": "船到河心，女人坐在船头，老周不敢回头",
        "pressure": {"deadline": "天亮前", "stake": "错过这一趟就再也找不到她", "opponent": "船行会的规矩"},
    }
    outline_text = (
        "<<<OUTLINE_JSON\n" + json.dumps(outline_json, ensure_ascii=False) + "\nOUTLINE_JSON>>>\n"
        "## 3. 节拍\n- 老周收船，女人上船。\n"
    )
    prose = "夜色压下来。" * 200  # 1200 字，超过 1000 字目标的 40%

    def fake_chat(messages, **kwargs):
        system = messages[0]["content"]
        if "章节设计编辑" in system:
            return {"text": outline_text, "model": "m-outline", "usage": {}}
        return {"text": prose, "model": "m-prose", "usage": {}}

    monkeypatch.setattr(writing, "chat", fake_chat)
    res = writing.generate_chapter(root, number=1)

    assert res["outline"]["title"] == "夜航"
    assert res["chars"] >= 1000
    assert (root / "chapters/001-夜航.md").is_file()
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    assert index[0]["number"] == 1
    assert index[0]["approved"] is False
    outlines = [r for r in read_jsonl(root / "ledger/outline.jsonl") if not r.get("__corrupt")]
    assert outlines[0]["beats"][0].startswith("拍1")
    assert "OUTLINE_JSON" not in outlines[0]["detail"]

    # 已有正文时不覆盖
    try:
        writing.generate_chapter(root, number=1)
    except ValueError as exc:
        assert "已经有正文" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("重复写同一章应当被拒绝")


def test_http_pipeline_blueprint_then_chapter(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    blueprint_text = "\n".join([
        "## 第一部分：全书大纲",
        "### 1. 全书层",
        "- 一句话故事核：老周想守住渡口，被一个自称女儿的乘客挡住。",
        "### 第1卷 无岸（第1-30章）",
        "- 任务与矛盾：老周要弄清乘客身份。",
        "## 第二部分：世界观",
        "### 1. 世界基底",
        "雾港没有对岸，渡船靠执念维持。",
    ])
    outline_json = {
        "chapter": 1,
        "title": "夜航",
        "beats": ["拍1：老周收船 → 女人上船 → 没有影子"],
        "mustInclude": ["断桨"],
        "mustAvoid": [],
        "openingState": "旧码头",
        "endingState": "河心",
        "pressure": {"deadline": "天亮前", "stake": "再也找不到她", "opponent": "船行"},
    }

    def fake_blueprint_chat(messages, **kwargs):
        return {"text": blueprint_text, "model": "m", "usage": {}}

    def fake_write_chat(messages, **kwargs):
        if "章节设计编辑" in messages[0]["content"]:
            return {"text": "<<<OUTLINE_JSON\n" + json.dumps(outline_json, ensure_ascii=False) + "\nOUTLINE_JSON>>>", "model": "m", "usage": {}}
        return {"text": "夜色压下来。" * 200, "model": "m", "usage": {}}

    monkeypatch.setattr(blueprint, "chat", fake_blueprint_chat)
    monkeypatch.setattr(writing, "chat", fake_write_chat)

    r = client.post("/api/projects/blueprint", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert "世界基底" in r.json()["worldText"]

    append_jsonl(root / "ledger/foreshadow.jsonl", {
        "id": "fs-test", "name": "断桨", "kind": "main", "plantedChapter": 1,
        "dueChapter": 5, "status": "open", "source": "测试", "at": "",
    })
    r = client.post("/api/projects/chapters/1/generate", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapter"]["number"] == 1
    assert body["outline"]["title"] == "夜航"
    assert (root / "chapters/001-夜航.md").is_file()
