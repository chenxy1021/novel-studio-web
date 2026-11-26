"""Route smoke tests against a synthetic book (no real manuscript needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import create, review
from app.main import app
from app.store import add_to_index, project_path

client = TestClient(app)


@pytest.fixture
def book(tmp_path) -> Path:
    books = tmp_path / "books"
    books.mkdir()
    old = create.books_root
    create.books_root = lambda: books
    try:
        root = Path(create.create_book(title="接口测试", target_chapters=20)["dir"])
    finally:
        create.books_root = old
    d = project_path(root, "chapters")
    d.mkdir(parents=True, exist_ok=True)
    text = "城里的广播响了，风从断桥那边过来。" * 120
    (d / "001-开场.md").write_text(text + "\n", encoding="utf-8")
    entry = review._entry_from_text(
        {"number": 1, "title": "开场", "file": "chapters/001-开场.md"}, text,
    )
    add_to_index(root, entry)
    return root


def test_ping():
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_projects_lists_books(book):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert "接口测试" in {b["title"] for b in r.json()["books"]}


def test_overview_of_book(book):
    r = client.get("/api/projects/overview", params={"dir": str(book)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "接口测试"
    assert len(body["chapters"]) == 1


def test_chapter_text(book):
    r = client.get("/api/projects/chapters/1", params={"dir": str(book)})
    assert r.status_code == 200
    assert r.json()["chars"] > 1000


def test_chapter_missing_404(book):
    r = client.get("/api/projects/chapters/9999", params={"dir": str(book)})
    assert r.status_code == 404


def test_rejects_non_book_dir(tmp_path):
    r = client.get("/api/projects/overview", params={"dir": str(tmp_path)})
    assert r.status_code == 400


def test_rejects_system_dir():
    r = client.get("/api/projects/overview", params={"dir": "/etc"})
    assert r.status_code == 403


def test_ledger_segments_folded(book):
    r = client.get("/api/projects/ledger/segments", params={"dir": str(book), "folded": "true"})
    assert r.status_code == 200
    assert r.json()["rows"] == []


@pytest.mark.parametrize("name", ["foreshadow", "timeline", "segments", "review", "usage", "dismissed", "outline"])
def test_all_ledgers_readable(name, book):
    r = client.get(f"/api/projects/ledger/{name}", params={"dir": str(book)})
    assert r.status_code == 200, r.text
