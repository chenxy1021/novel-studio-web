"""审阅写回路：存档 / 退回 / 废章恢复 / 正文保存 / 体检 / 改写。

全部在 tmp 书目录里跑，不碰作者的两本真书。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import review
from app.main import app

client = TestClient(app)

LONG = "他把最后一颗螺丝拧紧，塔顶的红灯亮起来。" * 120  # 约 2400 字
SHORT = "他只说了一句，就走下了塔。" * 12


def make_book(tmp_path: Path, text: str = LONG) -> Path:
    root = tmp_path / "书"
    (root / "chapters").mkdir(parents=True)
    (root / "ledger").mkdir()
    (root / "drafts").mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "测试书", "genre": "测试", "platform": "通用",
        "targetChapters": 100, "currentChapter": 1, "wordsPerChapter": 2000,
        "gate": {"phase": "writing", "chapter": 2, "reason": "", "at": ""},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "季恒", "want": "把塔修好", "fear": "停播", "voice": "短句"}],
        "rules": [],
    }, ensure_ascii=False), encoding="utf-8")
    body = f"chapters/001-第一段广播.md"
    (root / body).write_text(text, encoding="utf-8")
    (root / "chapters/index.json").write_text(json.dumps([{
        "number": 1, "title": "第一段广播", "file": body,
        "chars": len(text), "summary": "第一段广播。", "characters": ["季恒"],
        "approved": False, "chapterVerdict": "pass", "verdict": "良",
        "fixReasons": [], "dialogueRatio": 0.1,
    }], ensure_ascii=False), encoding="utf-8")
    return root


def test_check_chapter_reports_floor(tmp_path):
    root = make_book(tmp_path, SHORT)
    r = client.get("/api/projects/chapters/1/check", params={"dir": str(root)})
    assert r.status_code == 200
    body = r.json()
    assert body["pass"] is False
    assert any(f["code"] == "words-below" for f in body["findings"])


def test_archive_blocks_then_force(tmp_path):
    root = make_book(tmp_path, SHORT)
    r = client.post("/api/projects/chapters/1/archive", params={"dir": str(root)}, json={})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert isinstance(detail, dict) and detail["findings"]

    r = client.post("/api/projects/chapters/1/archive", params={"dir": str(root)}, json={"force": True})
    assert r.status_code == 200, r.text
    assert r.json()["approved"] == 1
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    assert index[0]["approved"] is True
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert project["gate"]["chapter"] == 2


def test_reject_list_restore(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/chapters/1/reject", params={"dir": str(root)}, json={"reason": "重写"})
    assert r.status_code == 200, r.text
    draft = r.json()["draftFile"]
    assert draft and (root / draft).is_file()
    assert json.loads((root / "chapters/index.json").read_text(encoding="utf-8")) == []

    rows = client.get("/api/projects/discarded", params={"dir": str(root)}).json()["rows"]
    assert rows and rows[0]["number"] == 1 and rows[0]["title"] == "第一段广播"

    r = client.post("/api/projects/discarded/restore", params={"dir": str(root)}, json={"draftFile": draft})
    assert r.status_code == 200, r.text
    assert r.json()["chapter"]["title"] == "第一段广播"
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    assert index[0]["number"] == 1
    assert index[0]["approved"] is False


def test_save_chapter_text_unapproves(tmp_path):
    root = make_book(tmp_path)
    client.post("/api/projects/chapters/1/archive", params={"dir": str(root)}, json={})
    r = client.put("/api/projects/chapters/1", params={"dir": str(root)},
                   json={"text": LONG + "补一句。"})
    assert r.status_code == 200, r.text
    assert r.json()["chapter"]["approved"] is False
    assert "补一句" in (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8")


def test_check_batch_shape(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/check-batch", params={"dir": str(root)}, json={"from": 1, "to": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == 1 and body["to"] == 1
    assert body["chapters"][0]["number"] == 1
    assert isinstance(body["blocking"], list)


def test_rewrite_uses_model_and_keeps_old_draft(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "改过的正文。" * 320, "model": "test-model",
        "usage": {"total_tokens": 123},
    })
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)},
                    json={"reason": "去掉总结句"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapter"]["approved"] is False
    assert "改过的正文" in body["text"]
    rows = client.get("/api/projects/discarded", params={"dir": str(root)}).json()["rows"]
    assert any("rewrite" in x["draftFile"] for x in rows)


def test_rewrite_model_failure_changes_nothing(tmp_path, monkeypatch):
    from app.llm import LLMError

    root = make_book(tmp_path)
    before = (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8")

    def boom(*a, **k):
        raise LLMError("模型没连上")

    monkeypatch.setattr(review, "chat", boom)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={})
    assert r.status_code == 502
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8") == before


def test_ai_check_merges_findings(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": '[{"severity":"mid","code":"voice","message":"季恒这句不像他","hint":"改短"}]',
        "model": "test-model", "usage": {"total_tokens": 10},
    })
    r = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert any(f["code"] == "voice" for f in r.json()["findings"])


def test_add_and_payoff_foreshadow(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/foreshadow", params={"dir": str(root)}, json={
        "name": "日志里多出的一行", "kind": "main",
        "plantedChapter": 3, "dueChapter": 12,
        "revealWho": "陈工", "hint": "第 7 章日志末尾出现乱码",
    })
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["id"] and row["status"] == "open"

    rows = client.get("/api/projects/ledger/foreshadow",
                      params={"dir": str(root), "folded": True}).json()["rows"]
    assert any(f["id"] == row["id"] and f["status"] == "open" for f in rows)

    r = client.post("/api/projects/foreshadow/payoff", params={"dir": str(root)},
                    json={"id": row["id"], "chapter": 12})
    assert r.status_code == 200, r.text

    rows = client.get("/api/projects/ledger/foreshadow",
                      params={"dir": str(root), "folded": True}).json()["rows"]
    paid = next(f for f in rows if f["id"] == row["id"])
    assert paid["status"] == "paid"
    assert paid["payoffChapter"] == 12

    again = client.post("/api/projects/foreshadow/payoff", params={"dir": str(root)},
                        json={"id": row["id"], "chapter": 13})
    assert again.status_code == 400


def test_add_foreshadow_rejects_bad_range(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/foreshadow", params={"dir": str(root)}, json={
        "name": "倒着收", "plantedChapter": 9, "dueChapter": 9,
    })
    assert r.status_code == 400


def test_rewrite_prompt_carries_platform_playbook(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    seen: dict[str, object] = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 320, "model": "test-model", "usage": {"total_tokens": 10}}

    monkeypatch.setattr(review, "chat", fake)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    prompt = "\n".join(m["content"] for m in seen["messages"])  # type: ignore[index]
    assert "平台打法" in prompt
    assert "章末钩子" in prompt
    assert "通用" in prompt
