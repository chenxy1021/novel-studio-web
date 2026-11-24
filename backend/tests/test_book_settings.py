"""书级写作参数（字数下限 / 每段章数）与「写后补设定」。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import create, review, segment, settings_gen
from app.main import app
from app.store import load_bible, read_index, save_bible, write_chapter, write_index

client = TestClient(app)


def _make_book(tmp_path: Path, **kw) -> Path:
    book = create.create_book(title=kw.pop("title", "测试书"), **kw)
    return Path(book["dir"])


def _seed_chapter(root: Path, n: int, text: str, summary: str = "") -> None:
    _, rel = write_chapter(root, n, f"第{n}章", text)
    rows = read_index(root)
    rows.append({
        "number": n, "title": f"第{n}章", "file": rel,
        "chars": len(text), "summary": summary, "approved": False,
    })
    write_index(root, rows)


def test_put_book_settings_persists_and_overview_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    root = _make_book(tmp_path, target_chapters=100)

    r = client.put(
        "/api/projects/book",
        json={"minChars": 2200, "segmentSize": 12},
        params={"dir": str(root)},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "minChars": 2200, "segmentSize": 12}

    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert project["minChars"] == 2200
    assert project["segmentSize"] == 12
    assert review.chapter_min_chars(project) == 2200

    over = client.get("/api/projects/overview", params={"dir": str(root)}).json()
    assert over["minChars"] == 2200
    assert over["segmentSize"] == 12


def test_put_book_settings_rejects_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    root = _make_book(tmp_path)

    assert client.put("/api/projects/book", json={"segmentSize": 2}, params={"dir": str(root)}).status_code == 400
    assert client.put("/api/projects/book", json={"segmentSize": 31}, params={"dir": str(root)}).status_code == 400
    assert client.put("/api/projects/book", json={"minChars": -1}, params={"dir": str(root)}).status_code == 400
    assert client.put("/api/projects/book", json={}, params={"dir": str(root)}).status_code == 400


def test_explicit_min_chars_overrides_short_book_default():
    # ≤50 章的短篇默认不限字数；作者显式写过就照作者的来。
    assert review.chapter_min_chars({"targetChapters": 20}) == 0
    assert review.chapter_min_chars({"targetChapters": 20, "minChars": 900}) == 900
    assert review.chapter_min_chars({"targetChapters": 20, "minChars": 0}) == 0
    assert review.chapter_min_chars({"targetChapters": 100, "minChars": 1500}) == 1500


def test_segment_plan_uses_project_segment_size(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    root = _make_book(tmp_path)
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["segmentSize"] = 6
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    plan = segment.plan_segment(root, frm=1)
    assert plan["to"] == 6
    assert len(plan["stages"]) >= 1


def test_supplement_only_adds_new_and_skips_known(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    root = _make_book(tmp_path)
    bible = load_bible(root)
    bible["characters"] = [{"name": "张三", "aliases": ["三哥"], "text": "老角色"}]
    save_bible(root, bible)
    _seed_chapter(root, 1, "张三走进旧码头，看见李四在等人。", summary="张三在旧码头遇到李四")

    captured: dict[str, object] = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return {
            "text": json.dumps({
                "characters": [{"name": "张三"}, {"name": "李四", "role": "码头工"}],
                "locations": [{"name": "旧码头", "geo": "城西河岸"}],
            }, ensure_ascii=False),
            "model": "fake",
        }

    monkeypatch.setattr(settings_gen, "chat", fake_chat)
    out = settings_gen.supplement_settings(root, recent=4)

    assert out["added"]["characters"] == 1
    assert out["added"]["locations"] == 1
    assert out["skipped"]["characters"] == 1
    assert out["chapters"] == [1]

    saved = load_bible(root)
    names = {c["name"] for c in saved["characters"]}
    assert names == {"张三", "李四"}
    assert [l["name"] for l in saved["locations"]] == ["旧码头"]

    # 提示词里要带上已有名字和最近正文，模型才知道什么算重复
    user = captured["messages"][1]["content"]  # type: ignore[index]
    assert "张三" in user and "三哥" in user
    assert "旧码头" in user


def test_supplement_requires_written_chapters(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    root = _make_book(tmp_path)
    r = client.post("/api/projects/settings/supplement", json={"recent": 4}, params={"dir": str(root)})
    assert r.status_code == 400
    assert "正文" in r.text
