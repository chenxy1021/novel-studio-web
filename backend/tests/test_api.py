"""Route smoke tests against the two real books (read-only)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_ping():
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_projects_lists_books():
    r = client.get("/api/projects")
    assert r.status_code == 200
    titles = {b["title"] for b in r.json()["books"]}
    expected = {"最后一座信号塔", "猎场第一百层"}
    if not expected <= titles:
        pytest.skip("两本参考书不都在书架上（可能被删到 .trash），这条用例依赖本机书稿")


def test_overview_of_signal_tower(signal_tower):
    r = client.get("/api/projects/overview", params={"dir": str(signal_tower)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "最后一座信号塔"
    assert len(body["chapters"]) == 10
    assert body["gate"]["phase"] == "writing"


def test_chapter_text(hunting_tower):
    r = client.get("/api/projects/chapters/68", params={"dir": str(hunting_tower)})
    assert r.status_code == 200
    assert r.json()["chars"] > 1000


def test_chapter_missing_404(hunting_tower):
    r = client.get("/api/projects/chapters/9999", params={"dir": str(hunting_tower)})
    assert r.status_code == 404


def test_rejects_non_book_dir(tmp_path):
    r = client.get("/api/projects/overview", params={"dir": str(tmp_path)})
    assert r.status_code == 400


def test_rejects_system_dir():
    r = client.get("/api/projects/overview", params={"dir": "/etc"})
    assert r.status_code == 403


def test_ledger_segments_folded(signal_tower):
    r = client.get("/api/projects/ledger/segments", params={"dir": str(signal_tower), "folded": "true"})
    assert r.status_code == 200
    assert r.json()["rows"][0]["from"] == 1


@pytest.mark.parametrize("name", ["foreshadow", "timeline", "segments", "review", "usage", "dismissed", "outline"])
def test_all_ledgers_readable(name, signal_tower):
    r = client.get(f"/api/projects/ledger/{name}", params={"dir": str(signal_tower)})
    assert r.status_code == 200, r.text
