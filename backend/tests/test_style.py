"""文风 v2 与写作技能开关（切片 1 / A 组）。全部在 tmp 书目录里跑。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.style import style_block
from app.main import app

client = TestClient(app)


def make_book(tmp_path: Path, *, style: dict | None = None, nuewen: bool = False) -> Path:
    root = tmp_path / "书"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "文风测试书",
        "platform": "generic",
        "nuewen": nuewen,
        "targetChapters": 100,
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [],
        "rules": [],
        "style": style or {},
    }, ensure_ascii=False), encoding="utf-8")
    return root


def get_style(root: Path) -> dict:
    r = client.get("/api/projects/style", params={"dir": str(root)})
    assert r.status_code == 200, r.text
    return r.json()


def put_style(root: Path, style: dict) -> dict:
    return client.put("/api/projects/style", params={"dir": str(root)}, json={"style": style})


def test_get_style_reads_legacy_fields_and_forces_v2(tmp_path):
    root = make_book(tmp_path, style={
        "pov": "第三人称限制",
        "tense": "过去时",
        "samples": [{"text": "雨落在铁皮上。"}],
        "banned": ["他很难过", "他很难过"],
        "notes": "情绪落在动作上。",
    })
    body = get_style(root)
    style = body["style"]
    assert style["version"] == 2
    assert style["pov"] == "第三人称限制"
    assert style["tense"] == "过去时"
    assert style["notes"] == "情绪落在动作上。"
    assert style["banned"] == ["他很难过"]  # 去重
    assert style["samples"][0]["text"] == "雨落在铁皮上。"
    # 缺省字段按空处理，不阻塞加载
    assert style["person"] == ""
    assert style["references"] == []
    assert body["source"] == "book"
    assert body["defaults"]["pov"] == "第三人称限制"


def test_get_style_empty_book_uses_platform_source(tmp_path):
    root = make_book(tmp_path)
    body = get_style(root)
    assert body["source"] == "platform"
    assert body["style"]["version"] == 2
    assert body["defaults"]["sentence"]


def test_put_style_merges_partially_and_sets_version_2(tmp_path):
    root = make_book(tmp_path, style={"pov": "第一人称", "notes": "旧说明"})
    r = put_style(root, {"rhythm": "紧", "version": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["style"]["version"] == 2
    assert body["style"]["rhythm"] == "紧"
    assert body["style"]["pov"] == "第一人称"  # 未提交字段不动
    assert body["style"]["notes"] == "旧说明"

    style = get_style(root)["style"]
    assert style["rhythm"] == "紧"
    assert style["pov"] == "第一人称"
    assert style["version"] == 2
    # 落盘的是 bible.json.style
    stored = json.loads((root / "bible.json").read_text(encoding="utf-8"))["style"]
    assert stored["rhythm"] == "紧"
    assert stored["version"] == 2


def test_put_style_rejects_invalid_samples(tmp_path):
    root = make_book(tmp_path)
    for bad in ("不是数组", [ {"note": "缺 text"} ], [123]):
        r = put_style(root, {"samples": bad})
        assert r.status_code == 400, (bad, r.text)
        detail = r.json()["detail"]
        assert detail["code"] == "STYLE_INVALID"
        assert detail["field"] == "samples"


def test_put_style_rejects_non_string_banned_and_references(tmp_path):
    root = make_book(tmp_path)
    for field in ("banned", "references"):
        r = put_style(root, {field: [{"author": "某人"}]})
        assert r.status_code == 400, (field, r.text)
        assert r.json()["detail"]["field"] == field
    r = put_style(root, {"banned": "不是数组"})
    assert r.status_code == 400


def test_writing_skills_defaults_and_partial_merge(tmp_path):
    root = make_book(tmp_path)
    r = client.get("/api/projects/writing-skills", params={"dir": str(root)})
    assert r.status_code == 200, r.text
    skills = r.json()["skills"]
    assert skills == {
        "deai": True, "dialogue": True, "scene": True, "hook": True,
        "continuity": True, "platform": True, "nuewen": False, "styleSamples": True,
    }

    r = client.put("/api/projects/writing-skills", params={"dir": str(root)},
                   json={"skills": {"scene": False}})
    assert r.status_code == 200, r.text
    merged = r.json()["skills"]
    assert merged["scene"] is False
    assert merged["deai"] is True  # 未提交键保持默认

    again = client.get("/api/projects/writing-skills", params={"dir": str(root)}).json()["skills"]
    assert again["scene"] is False
    assert again["deai"] is True
    stored = json.loads((root / "project.json").read_text(encoding="utf-8"))["writingSkills"]
    assert stored["scene"] is False
    assert len(stored) == 8


def test_writing_skills_nuewen_forced_false_for_non_nuewen_book(tmp_path):
    root = make_book(tmp_path, nuewen=False)
    r = client.put("/api/projects/writing-skills", params={"dir": str(root)},
                   json={"skills": {"nuewen": True}})
    assert r.status_code == 200, r.text
    assert r.json()["skills"]["nuewen"] is False
    # 内存/磁盘里都不会留下 true
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["writingSkills"]["nuewen"] is False


def test_writing_skills_unknown_key_is_400(tmp_path):
    root = make_book(tmp_path)
    r = client.put("/api/projects/writing-skills", params={"dir": str(root)},
                   json={"skills": {"bogus": True}})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "SKILL_INVALID"
    assert detail["field"] == "skills"


def test_style_block_override_wins_over_book():
    book = {"pov": "第三人称限制", "banned": ["他很难过"], "rhythm": "缓"}
    block = style_block(book, {"banned": ["空气仿佛凝固"], "rhythm": "紧"})
    assert "第三人称限制" in block
    assert "空气仿佛凝固" in block
    assert "他很难过" not in block  # 覆盖后不再出现书默认
    assert "节奏：紧" in block
    assert "不得因文风改变" in block  # 事实与表达分离
