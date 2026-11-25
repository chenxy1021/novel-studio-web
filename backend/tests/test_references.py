"""参考资料包与提示词注入（切片 2）。全部离线，只测 pack 组装与消息构建。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain import references, writing
from app.store import load_bible, load_project, save_bible, save_project


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def make_book(tmp_path: Path) -> Path:
    root = tmp_path / "书"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "雾港纪事",
        "genre": "悬疑·民俗",
        "platform": "generic",
        "targetChapters": 10,
        "wordsPerChapter": 1000,
        "outlineText": "### 第1卷 起（第1-10章）\n- 老周与阿雾在雾港对峙。",
        "worldText": "雾港没有对岸。" * 500,  # 3500 字，用于验证截断
        "logline": "渡船每夜多载一个不存在的人。",
    }, ensure_ascii=False), encoding="utf-8")

    (root / "bible.json").write_text(json.dumps({
        "characters": [
            {"name": "老周", "role": "摆渡人", "want": "守住渡口", "fear": "对岸不存在"},
            {"name": "阿雾", "role": "乘客", "want": "找回名字"},
        ],
        "rules": [{"name": "摆渡不能回头", "text": "回头就再也靠不了岸", "cost": "失去渡口"}],
        "world": [{"name": "雾港", "text": "没有对岸，靠执念维持。"}],
        "factions": [{"name": "船行会", "text": "控制所有渡船", "hiddenRules": "欠命要还"}],
        "locations": [{"name": "旧码头", "text": "终年大雾", "accessRules": "只许夜航"}],
        "items": [{"name": "断桨", "text": "老周的旧桨", "holder": "老周", "state": "裂了"}],
        "style": {"rhythm": "紧"},
    }, ensure_ascii=False), encoding="utf-8")

    chapters = root / "chapters"
    chapters.mkdir()
    (chapters / "001-夜航.md").write_text("夜色压下来，阿雾上了船。" * 20, encoding="utf-8")
    (chapters / "002-回港.md").write_text("船回到旧码头，阿雾没有下船。" * 20, encoding="utf-8")
    (chapters / "index.json").write_text(json.dumps([
        {"number": 1, "title": "夜航", "file": "chapters/001-夜航.md",
         "summary": "老周遇见没有影子的阿雾", "approved": True},
        {"number": 2, "title": "回港", "file": "chapters/002-回港.md",
         "summary": "阿雾留在船上", "approved": False},
    ], ensure_ascii=False), encoding="utf-8")

    _write_jsonl(root / "ledger/volumes.json",
                 [{"volumes": [{"title": "第1卷 起", "from": 1, "to": 10}], "source": "outline"}])
    _write_jsonl(root / "ledger/segments.jsonl", [{
        "from": 1, "to": 10,
        "plan": {"stages": [{
            "chapters": [1, 2, 3], "goal": "认清阿雾身份", "turn": "发现她没有影子",
            "pace": "慢", "places": ["旧码头"],
            "foreshadow": {"plant": ["断桨"], "payoff": []},
        }]},
    }])
    _write_jsonl(root / "ledger/foreshadow.jsonl", [{
        "id": "fs1", "name": "断桨", "plantedChapter": 1, "dueChapter": 3,
        "status": "open", "plantBeat": "船头", "hint": "夜里会自己响",
    }])
    _write_jsonl(root / "ledger/timeline.jsonl", [{
        "chapter": 1, "storyTime": "第一夜", "place": "旧码头", "event": "阿雾上船",
        "kind": "event", "characters": ["老周", "阿雾"],
    }])
    _write_jsonl(root / "ledger/memory.jsonl", [
        {"kind": "chapter", "chapter": 1, "summary": "老周载上阿雾", "events": ["阿雾上船"],
         "state": "船在河心", "knows": [{"who": "老周", "learned": "阿雾没有影子"}],
         "relations": [{"a": "老周", "b": "阿雾", "change": "互相试探"}]},
        {"kind": "chapter", "chapter": 2, "summary": "阿雾留在船上", "events": ["阿雾拒绝下船"],
         "state": "回到旧码头", "relations": [{"a": "老周", "b": "阿雾", "change": "开始信任"}]},
    ])
    _write_jsonl(root / "ledger/outline.jsonl", [{
        "chapter": 2, "title": "回港", "beats": ["拍1：船靠岸"], "source": "ai", "model": "m", "at": "",
    }])
    (root / "ledger/relations.json").write_text(json.dumps({
        "edges": [{"a": "老周", "b": "阿雾", "state": "互相试探", "chapter": 1}],
    }, ensure_ascii=False), encoding="utf-8")
    return root


def _sec(pack: dict, key: str) -> dict:
    return next(s for s in pack["sections"] if s["key"] == key)


def _user(messages: list[dict]) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def test_pack_sections_counts_and_missing(tmp_path):
    root = make_book(tmp_path)
    pack = references.build_reference_pack(root, 3)

    keys = [s["key"] for s in pack["sections"]]
    for key in ("volume-outline", "stage", "foreshadow-this", "foreshadow-open",
                "characters", "character-state", "relations", "rules", "world",
                "factions", "locations", "items", "chapter-memory",
                "volume-memory", "timeline", "prev-tail", "style", "platform"):
        assert key in keys, key
    # 这本书没开「虐文」技能：面板和提示词都不该出现这段。
    assert "nuewen" not in keys

    assert _sec(pack, "factions")["count"] == 1
    assert _sec(pack, "locations")["count"] == 1
    assert _sec(pack, "items")["count"] == 1
    assert _sec(pack, "character-state")["count"] == 2  # 老周 / 阿雾 各一行
    assert _sec(pack, "relations")["count"] == 1
    # 同一对在章记忆里变过两次：参考资料要取最新状态，而不是开书底稿。
    assert "开始信任" in _sec(pack, "relations")["text"]
    assert _sec(pack, "chapter-memory")["count"] == 2
    assert _sec(pack, "timeline")["count"] == 1
    assert _sec(pack, "foreshadow-this")["count"] == 1

    # 没有卷记忆 → 标灰；本章伏笔是可选段，不标灰。
    assert _sec(pack, "volume-memory")["missing"] is True
    assert _sec(pack, "foreshadow-this")["optional"] is True

    assert pack["summary"]["sections"] == len(pack["sections"])
    assert pack["summary"]["items"] == sum(s["count"] for s in pack["sections"])
    assert pack["title"] == "第3章"


def test_pack_truncates_long_sections(tmp_path):
    root = make_book(tmp_path)
    pack = references.build_reference_pack(root, 3)
    world = _sec(pack, "world")
    assert world["truncated"] is True
    assert world["chars"] > references.SECTION_LIMIT
    assert len(world["text"]) == references.SECTION_LIMIT
    assert len(world["preview"]) <= references.PREVIEW_LIMIT


def test_render_block_focus_first_and_contains_world_items(tmp_path):
    root = make_book(tmp_path)
    focus = [{"type": "item", "key": "断桨", "label": "断桨要再出现"}]
    pack = references.build_reference_pack(root, 3, focus=focus)
    block = references.render_reference_block(pack, stage="prose")

    assert block.startswith("【本章额外强调】")
    assert "断桨要再出现" in block
    assert "船行会" in block
    assert "【物品·断桨】" in block
    assert "已按预算截断" in block  # 世界观超长


def test_detail_messages_include_new_sections_and_respect_skills(tmp_path):
    root = make_book(tmp_path)
    project = load_project(root)
    bible = load_bible(root)
    volume_block, volume = references.volume_slice(project["outlineText"], references.load_volumes(root), 3)
    stage = references.stage_for(root, 3)

    user = _user(writing._detail_messages(
        project, bible, root=root, chapter=3, volume_block=volume_block,
        volume=volume, stage=stage, recent="（暂无）",
    ))
    for phrase in ("【势力】", "【物品】", "【角色状态", "【故事内时间线】", "【人物关系】", "【近章记忆"):
        assert phrase in user, phrase
    assert "船行会" in user and "断桨" in user
    assert "【平台打法】" in user

    # 关掉平台与连续性：生成提示词不再主动展开对应模块。
    off = {**project, "writingSkills": {"platform": False, "continuity": False}}
    user_off = _user(writing._detail_messages(
        off, bible, root=root, chapter=3, volume_block=volume_block,
        volume=volume, stage=stage, recent="（暂无）",
    ))
    assert "【平台打法】" not in user_off
    assert "【连续性方法" not in user_off


def test_prose_module_titles_follow_scene_dialogue_switches(tmp_path):
    root = make_book(tmp_path)
    project = load_project(root)
    bible = load_bible(root)
    outline = {"title": "夜航", "beats": ["拍1：老周收船"], "mustInclude": [], "mustAvoid": []}

    on = _user(writing._prose_messages(project, bible, root=root, chapter=3, outline=outline))
    assert "# 场景落地" in on
    assert "# 对话写作" in on
    assert "# 章末钩子" in on

    off_project = {**project, "writingSkills": {"scene": False, "dialogue": False}}
    off = _user(writing._prose_messages(off_project, bible, root=root, chapter=3, outline=outline))
    assert "# 场景落地" not in off
    assert "# 对话写作" not in off
    assert "# 章末钩子" in off  # 只关了 scene/dialogue

    # focus 仍然置顶。
    focused = _user(writing._prose_messages(
        project, bible, root=root, chapter=3, outline=outline,
        focus=[{"type": "rule", "key": "r1", "label": "摆渡不能回头"}],
    ))
    assert focused.startswith("【本章额外强调")


def test_references_routes_return_same_pack(tmp_path):
    """面板读到的条数必须与提示词同源；preview 只改强调项，不落盘。"""
    from fastapi.testclient import TestClient

    from app.main import app

    root = make_book(tmp_path)
    client = TestClient(app)

    got = client.get("/api/projects/chapters/1/references", params={"dir": str(root)})
    assert got.status_code == 200, got.text
    pack = got.json()
    keys = [s["key"] for s in pack["sections"]]
    for key in ("volume-outline", "stage", "factions", "locations", "items",
                "chapter-memory", "timeline", "style", "platform"):
        assert key in keys, key
    assert pack["summary"]["sections"] == len(pack["sections"])
    assert "【势力】" in pack["prompt"]

    preview = client.post(
        "/api/projects/chapters/1/references/preview",
        params={"dir": str(root)},
        json={"focus": [{"type": "rule", "key": "r1", "label": "摆渡不能回头"}]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["sections"][0]["key"] == "extra-focus"
    assert "摆渡不能回头" in body["prompt"]
    assert (root / "chapters/001-夜航.md").is_file()  # 预览不写稿

    # 面板带着本批技能开关来取包：关掉的段不应出现。
    off = client.get(
        "/api/projects/chapters/1/references",
        params={"dir": str(root), "skills": json.dumps({"platform": False})},
    )
    assert off.status_code == 200, off.text
    assert "platform" not in [s["key"] for s in off.json()["sections"]]
    assert "【平台打法" not in off.json()["prompt"]

    bad = client.get(
        "/api/projects/chapters/1/references",
        params={"dir": str(root), "skills": "[1,2]"},
    )
    assert bad.status_code == 400


def test_batch_skill_override_merges_book_defaults():
    project = {"title": "书", "nuewen": False, "writingSkills": {"dialogue": True, "scene": False}}
    merged = writing._apply_skill_override(project, {"dialogue": False, "scene": True, "nuewen": True})
    skills = merged["writingSkills"]
    assert skills["dialogue"] is False
    assert skills["scene"] is True
    assert skills["nuewen"] is False  # 非虐文书强制关
    assert writing._apply_skill_override(project, None) is project  # 没传就不复制


def test_outline_and_prose_prompts_inject_world_depth_and_foreshadow(tmp_path):
    """「本章资料」面板里有的段落，细纲和正文的提示词也必须真的用上。"""
    root = make_book(tmp_path)
    bible = load_bible(root)
    bible.update({
        "powerSystem": {
            "name": "摆渡阶",
            "levels": [{"name": "引路人", "trait": "能看见空船"}],
            "costs": "每渡一次少一年寿命",
        },
        "society": {"currency": "冥钞", "taboo": "夜里不喊乘客的名字"},
        "history": [{"era": "旧朝", "event": "断桥之战", "impact": "两岸断了往来"}],
        "glossary": [{"term": "空返", "meaning": "船不载客回程"}],
    })
    save_bible(root, bible)

    project = load_project(root)
    bible = load_bible(root)
    volume_block, volume = references.volume_slice(project["outlineText"], references.load_volumes(root), 3)
    stage = references.stage_for(root, 3)
    outline = {"title": "夜航", "beats": ["拍1：老周收船"], "mustInclude": [], "mustAvoid": []}

    detail = _user(writing._detail_messages(
        project, bible, root=root, chapter=3, volume_block=volume_block,
        volume=volume, stage=stage, recent="（暂无）",
    ))
    prose = _user(writing._prose_messages(project, bible, root=root, chapter=3, outline=outline))

    for user in (detail, prose):
        for phrase in ("【力量体系", "摆渡阶", "【社会常识", "冥钞", "【大事记", "断桥之战", "【术语表", "空返"):
            assert phrase in user, phrase

    # 正文还要知道本章该埋/该收哪条伏笔，以及自己落在哪一段。
    assert "【本章伏笔" in prose and "断桨" in prose
    assert "【本卷大纲切片" in prose
    assert "【本章在段落纲里的位置" in prose and "认清阿雾身份" in prose
    assert "【连贯性（事实层，不得违反）】" in prose


def test_pack_panel_matches_prompt_when_skills_toggle(tmp_path):
    """技能开关只在一个地方判定：pack 里有哪段，提示词里就有哪段。"""
    root = make_book(tmp_path)
    project = load_project(root)
    bible = load_bible(root)

    # 默认：平台开、虐文关 → 两边都不该有【虐文原则】。
    pack = references.build_reference_pack(root, 3)
    keys = [s["key"] for s in pack["sections"]]
    assert "platform" in keys and "nuewen" not in keys

    # 显式传入的技能覆盖也要同时作用到 pack（面板用）。
    pack_off = references.build_reference_pack(
        root, 3, skills={"platform": False, "nuewen": True},
    )
    keys_off = [s["key"] for s in pack_off["sections"]]
    assert "platform" not in keys_off
    assert "nuewen" in keys_off

    # 书的设置：关平台、开虐文 → 提示词跟着走。
    project["nuewen"] = True
    project["writingSkills"] = {"platform": False, "nuewen": True}
    save_project(root, project)
    outline = {"title": "夜航", "beats": ["拍1：老周收船"], "mustInclude": [], "mustAvoid": []}
    user = _user(writing._prose_messages(project, bible, root=root, chapter=3, outline=outline))
    assert "【平台打法" not in user
    assert "【虐文原则" in user

    pack_on = references.build_reference_pack(root, 3)
    keys_on = [s["key"] for s in pack_on["sections"]]
    assert "platform" not in keys_on and "nuewen" in keys_on


def test_long_book_keeps_old_chapters_in_memory_section(tmp_path):
    """写到第 201 章时，前情不能只剩最近 8 章：更早的章仍有一句，更早的另有兜底说明。"""
    root = make_book(tmp_path)
    index = [
        {"number": n, "title": f"第{n}章", "file": f"chapters/{n:03d}.md", "chars": 1200,
         "summary": f"第{n}章：老周又送走一个人。", "characters": ["老周", "阿雾"] if n == 10 else ["老周"]}
        for n in range(1, 201)
    ]
    (root / "chapters").mkdir(exist_ok=True)
    (root / "chapters/index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    _write_jsonl(root / "ledger/memory.jsonl", [
        {"kind": "chapter", "chapter": n, "summary": f"第{n}章：老周又送走一个人。",
         "events": [f"事件{n}"], "state": f"船在第{n}个渡口"}
        for n in range(1, 201)
    ])

    pack = references.build_reference_pack(root, 201)
    memory = _sec(pack, "chapter-memory")
    assert memory["count"] == 200                     # 覆盖全部已写章节
    assert "前情一句一章" in memory["text"]            # 更早的 80 章仍有一句
    assert "第113章" in memory["text"]
    assert "第 1-112 章" in memory["text"]            # 更早的明确说明已滑出，不假装记得
    assert memory["text"].count("\n") >= 60
    assert len(memory["text"]) <= references.ECHO_BUDGET

    # 强调一个只在第 10 章出现的说法 → 远章被单独调出，而不是被一句摘要带走。
    focused = references.build_reference_pack(root, 201, focus=[{"key": "阿雾", "label": "阿雾的来历"}])
    assert focused["sections"][0]["key"] == "extra-focus"
    focused_mem = _sec(focused, "chapter-memory")["text"]
    assert "第10章" in focused_mem
    assert "与本章相关，单独调出" in focused_mem

    # 提示词里也不该再出现已删除的「已存档章摘要」段。
    user = _user(writing._prose_messages(
        load_project(root), load_bible(root), root=root, chapter=201,
        outline={"title": "第201章", "beats": ["拍1"], "mustInclude": [], "mustAvoid": []},
    ))
    assert "已存档章摘要" not in user
    assert "前情一句一章" in user
