"""新书脚手架 + 回收站恢复。全部在 tmp 目录里跑。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import create
from app.main import app

client = TestClient(app)


def test_create_book_scaffolds_book_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    r = client.post("/api/projects/create", json={
        "title": "新书试验", "genre": "末世", "platform": "fanqie",
        "targetChapters": 80, "wordsPerChapter": 0,
        "logline": "全城只有一座楼还能发令", "theme": "发令权归谁",
    })
    assert r.status_code == 200, r.text
    book = r.json()["book"]
    root = Path(book["dir"])
    assert root.name == "新书试验"
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert project["title"] == "新书试验"
    assert project["platform"] == "番茄小说"
    assert project["targetChapters"] == 80
    assert project["wordsPerChapter"] == 2000  # 平台下限兜底
    assert project["gate"]["phase"] == "planning"
    assert (root / "bible.json").is_file()
    assert json.loads((root / "chapters/index.json").read_text(encoding="utf-8")) == []


def test_create_book_requires_title(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    r = client.post("/api/projects/create", json={"title": "   "})
    assert r.status_code == 400


def test_delete_book_is_permanent(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    book = create.create_book(title="删掉的书", target_chapters=20)
    root = Path(book["dir"])

    r = client.post("/api/projects/delete", json={"dir": str(root), "confirm": "错的书名"})
    assert r.status_code == 400
    assert root.is_dir()

    r = client.post("/api/projects/delete", json={"dir": str(root), "confirm": "删掉的书"})
    assert r.status_code == 200, r.text
    assert not root.exists()
    assert not (tmp_path / ".trash").exists()
