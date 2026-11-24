"""虐文骨架生成：走模型、落 ledger/nuewen.jsonl、读回最新一条。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import create, nuewen
from app.main import app

client = TestClient(app)


def test_nuewen_plan_generates_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    book = create.create_book(
        title="虐文试验", genre="古言", platform="fanqie",
        logline="她把唯一的退路让给了他，他却用这条路去救别人。",
        target_chapters=60,
    )
    seen: dict[str, object] = {}

    def fake_chat(messages, **kwargs):
        seen["messages"] = messages
        return {
            "text": "## 人物反转表\n\n| 角色 | 最 | 反转 |\n| --- | --- | --- |\n" + "细节" * 120,
            "model": "test-model",
            "usage": {"total_tokens": 42},
        }

    monkeypatch.setattr(nuewen, "chat", fake_chat)
    r = client.post(
        "/api/projects/nuewen/plan",
        params={"dir": book["dir"]},
        json={"instruction": "前三章必须见血"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "人物反转表" in body["text"]
    assert body["model"] == "test-model"

    prompt = "\n".join(m["content"] for m in seen["messages"])  # type: ignore[index]
    assert "最想活的死" in prompt
    assert "番茄小说" in prompt
    assert "前三章必须见血" in prompt

    saved = Path(book["dir"]) / "ledger/nuewen.jsonl"
    assert saved.is_file() and "人物反转表" in saved.read_text(encoding="utf-8")

    got = client.get("/api/projects/nuewen", params={"dir": book["dir"]})
    assert got.status_code == 200
    assert got.json()["text"] == body["text"]


def test_nuewen_plan_rejects_short_model_output(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    book = create.create_book(title="短输出", target_chapters=20)
    monkeypatch.setattr(nuewen, "chat", lambda *a, **k: {"text": "太短", "model": "t", "usage": {}})
    r = client.post("/api/projects/nuewen/plan", params={"dir": book["dir"]}, json={})
    assert r.status_code == 400


def test_nuewen_mode_toggles_project_and_rewrite_prompt(tmp_path, monkeypatch):
    from app.domain import review
    import json

    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    book = create.create_book(title="虐文模式", platform="fanqie", target_chapters=50)
    root = Path(book["dir"])

    r = client.post("/api/projects/nuewen/mode", params={"dir": str(root)}, json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert project["nuewen"] is True
    assert client.get("/api/projects/nuewen", params={"dir": str(root)}).json()["enabled"] is True

    # 建一章正文，才能走改写提示词
    (root / "chapters/001-第一章.md").write_text("他走进雨里。" * 200, encoding="utf-8")
    (root / "chapters/index.json").write_text(json.dumps([{
        "number": 1, "title": "第一章", "file": "chapters/001-第一章.md",
        "chars": 1400, "summary": "", "characters": [], "approved": False,
        "chapterVerdict": "pass", "verdict": "良", "fixReasons": [], "dialogueRatio": 0.0,
    }], ensure_ascii=False), encoding="utf-8")

    seen: dict[str, object] = {}

    def fake_chat(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 320, "model": "t", "usage": {}}

    monkeypatch.setattr(review, "chat", fake_chat)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    prompt = "\n".join(m["content"] for m in seen["messages"])  # type: ignore[index]
    assert "虐文原则" in prompt
    assert "最想活的死" in prompt
