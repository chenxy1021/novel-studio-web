"""作家文风预设（切片 1 / D 组）。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.style import style_block
from app.domain.style_presets import PRESETS, get_preset
from app.main import app

client = TestClient(app)

EXPECTED_IDS = {
    "aiqianshuidewuzhe", "chendong", "enyang", "liucixin",
    "sanjiuyinyu", "maoni", "fenghuo", "yuhua",
}
ADVISOR_IDS = {"maoni", "fenghuo", "yuhua"}


def make_book(tmp_path: Path, *, style: dict | None = None) -> Path:
    root = tmp_path / "预设书"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "预设测试书", "platform": "generic", "targetChapters": 100,
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [], "rules": [], "style": style or {},
    }, ensure_ascii=False), encoding="utf-8")
    return root


def get_style(root: Path) -> dict:
    r = client.get("/api/projects/style", params={"dir": str(root)})
    assert r.status_code == 200, r.text
    return r.json()["style"]


def test_presets_list_shape():
    r = client.get("/api/projects/style/presets")
    assert r.status_code == 200, r.text
    presets = r.json()["presets"]
    assert len(presets) == 8
    ids = [p["id"] for p in presets]
    assert len(set(ids)) == 8
    assert set(ids) == EXPECTED_IDS
    assert all(p["applicable"] is True for p in presets)
    assert {p["id"] for p in presets if p["advisor"] is True} == ADVISOR_IDS
    assert sum(1 for p in presets if p["kind"] == "prose") == 5
    assert sum(1 for p in presets if p["kind"] == "prose+advisor") == 3
    for preset in presets:
        assert preset["name"]
        assert preset["summary"]
        assert 4 <= len(preset["traits"]) <= 6
        assert preset["fields"]["pov"]
        assert isinstance(preset["fields"]["banned"], list)
        # 每家预设自带一段核对过出处的样章，选预设即可补入。
        assert len(preset["samples"]) == 1
        sample = preset["samples"][0]
        assert sample["text"] and len(sample["text"]) <= 300
        assert sample["label"] and len(sample["label"]) <= 12
        assert "出处：https://" in sample["note"]


def test_preset_fills_samples_when_book_has_none(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "yuhua"})
    assert r.status_code == 200, r.text
    style = r.json()["style"]
    assert len(style["samples"]) == 1
    assert style["samples"][0]["text"].startswith("我比现在年轻十岁的时候")
    assert "《活着》" in style["samples"][0]["label"]
    assert style["samples"][0]["origin"] == "preset"
    assert "https://" in style["samples"][0]["note"]
    # 出处只做说明，不进入提示词。
    block = style_block(style, stage="prose")
    assert "我比现在年轻十岁的时候" in block
    assert "https://" not in block


def test_preset_fill_only_keeps_author_fields(tmp_path):
    root = make_book(tmp_path, style={
        "pov": "第一人称", "rhythm": "缓", "notes": "作者自己的说明",
    })
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "chendong"})
    assert r.status_code == 200, r.text
    style = r.json()["style"]
    assert style["presetId"] == "chendong"
    assert style["pov"] == "第一人称"        # 作者已填，不覆盖
    assert style["rhythm"] == "缓"
    assert style["notes"] == "作者自己的说明"
    assert style["sentence"] == get_preset("chendong")["fields"]["sentence"]  # 空字段被补上
    assert "现代网络梗" in style["banned"]

    assert get_style(root)["presetId"] == "chendong"


def test_switching_preset_replaces_preset_sample(tmp_path):
    root = make_book(tmp_path)
    r1 = client.post("/api/projects/style/preset", params={"dir": str(root)},
                     json={"id": "yuhua"})
    assert r1.status_code == 200, r1.text
    assert "《活着》" in r1.json()["style"]["samples"][0]["label"]
    assert r1.json()["style"]["samples"][0]["origin"] == "preset"

    r2 = client.post("/api/projects/style/preset", params={"dir": str(root)},
                     json={"id": "chendong"})
    assert r2.status_code == 200, r2.text
    samples = r2.json()["style"]["samples"]
    assert len(samples) == 1
    assert "《遮天》" in samples[0]["label"]
    assert "生命是世间最伟大的奇迹" in samples[0]["text"]


def test_legacy_preset_sample_without_origin_is_replaced(tmp_path):
    # 旧版本写进去的样章没有 origin，靠正文命中预设样章来识别。
    legacy = {"text": get_preset("yuhua")["samples"][0]["text"], "label": "《活着》开场"}
    root = make_book(tmp_path, style={"samples": [legacy]})
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "chendong"})
    assert r.status_code == 200, r.text
    assert "《遮天》" in r.json()["style"]["samples"][0]["label"]


def test_manual_sample_survives_preset_switch(tmp_path):
    manual = {"text": "我自己粘的一段样章。", "label": "手填", "origin": "manual"}
    root = make_book(tmp_path, style={"samples": [manual]})
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "chendong"})
    assert r.status_code == 200, r.text
    samples = r.json()["style"]["samples"]
    assert samples[0] == manual
    assert "《遮天》" in samples[1]["label"]


def test_mixed_samples_keep_manual_and_swap_preset(tmp_path):
    manual = {"text": "我自己粘的一段样章。", "label": "手填", "origin": "manual"}
    legacy = {"text": get_preset("yuhua")["samples"][0]["text"], "label": "《活着》开场"}
    root = make_book(tmp_path, style={"samples": [manual, legacy]})
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "chendong"})
    assert r.status_code == 200, r.text
    samples = r.json()["style"]["samples"]
    assert samples[0] == manual
    assert len(samples) == 2
    assert "《遮天》" in samples[1]["label"]


def test_preset_overwrite_keeps_manual_samples(tmp_path):
    samples = [{"text": "这是样章，必须保留。", "label": "开场", "origin": "manual"}]
    root = make_book(tmp_path, style={
        "pov": "第一人称", "rhythm": "缓", "notes": "作者自己的说明",
        "banned": ["自定义禁用"], "samples": samples,
    })
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "chendong", "overwrite": True})
    assert r.status_code == 200, r.text
    style = r.json()["style"]
    preset = get_preset("chendong")["fields"]
    assert style["pov"] == preset["pov"]
    assert style["rhythm"] == preset["rhythm"]
    assert style["notes"] == preset["notes"]
    assert style["banned"] == preset["banned"]
    assert style["samples"][0] == samples[0]  # 手填样章不丢
    assert "《遮天》" in style["samples"][1]["label"]  # 预设样章照常补入
    assert style["presetId"] == "chendong"


def test_unknown_preset_id_400(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/style/preset", params={"dir": str(root)},
                    json={"id": "not-a-writer"})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "STYLE_INVALID"
    assert detail["field"] == "id"

    r = client.put("/api/projects/style", params={"dir": str(root)},
                   json={"style": {"presetId": "not-a-writer"}})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["field"] == "presetId"


def test_render_style_includes_preset_reference_without_samples():
    block = style_block(
        {"presetId": "chendong", "samples": [{"text": "样章原文不应出现。"}]},
        stage="outline",
    )
    assert "【文风参照·辰东】" in block
    assert "只参考写法，不复制原句；本书字段优先" in block
    assert "参照：宏大意象与时空尺度" in block
    assert block.count("参照：") <= 6
    assert "样章原文不应出现" not in block
