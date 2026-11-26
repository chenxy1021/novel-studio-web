"""批量存档与进程内并发保护（切片 1 / C 组）。全部离线。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import runs, writing
from app.main import app

client = TestClient(app)

LONG = "他把最后一颗螺丝拧紧，楼顶的顶灯亮起来。" * 120  # 约 2160 字


def make_archive_book(tmp_path: Path, *, target: int = 100, chapters: tuple[int, ...] = (1, 2)) -> Path:
    root = tmp_path / "存档书"
    (root / "chapters").mkdir(parents=True)
    (root / "ledger").mkdir()
    (root / "drafts").mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "存档测试书", "genre": "测试", "platform": "通用",
        "targetChapters": target, "currentChapter": max(chapters),
        "wordsPerChapter": 2000,
        "gate": {"phase": "writing", "chapter": max(chapters) + 1, "reason": "", "at": ""},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "陆行", "want": "把楼修好"}], "rules": [],
    }, ensure_ascii=False), encoding="utf-8")

    index = []
    for n in chapters:
        rel = f"chapters/{n:03d}-第{n}章.md"
        (root / rel).write_text(LONG, encoding="utf-8")
        index.append({
            "number": n, "title": f"第{n}章", "file": rel, "chars": 2160,
            "summary": "摘要", "characters": ["陆行"], "approved": False,
            "chapterVerdict": "pass", "verdict": "良", "fixReasons": [],
            "dialogueRatio": 0.1,
        })
    (root / "chapters/index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return root


def make_writing_book(tmp_path: Path, name: str = "写作书") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": name, "genre": "悬疑", "platform": "generic",
        "targetChapters": 10, "wordsPerChapter": 1000,
        "outlineText": "### 第1卷 起（第1-10章）\n老周与阿雾。",
        "worldText": "雾港没有对岸。",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "老周"}], "rules": [], "style": {},
    }, ensure_ascii=False), encoding="utf-8")
    return root


OUTLINE_JSON = {
    "chapter": 1, "title": "夜航",
    "beats": ["拍1：老周收船 → 女人上船 → 没有影子"],
    "mustInclude": ["断桨"], "mustAvoid": [],
    "openingState": "旧码头", "endingState": "河心",
    "pressure": {"deadline": "天亮前", "stake": "错过这一趟", "opponent": "船行会"},
}
OUTLINE_TEXT = (
    "<<<OUTLINE_JSON\n" + json.dumps(OUTLINE_JSON, ensure_ascii=False) + "\nOUTLINE_JSON>>>\n"
    "## 3. 节拍\n- 老周收船。\n"
)


def fake_chat(messages, **kwargs):
    if "章节设计编辑" in messages[0]["content"]:
        return {"text": OUTLINE_TEXT, "model": "m-outline", "usage": {}}
    return {"text": "夜色压下来。" * 200, "model": "m-prose", "usage": {}}


# --------------------------------- 批量存档 ---------------------------------


def test_archive_batch_partial_failure(tmp_path):
    root = make_archive_book(tmp_path, chapters=(1, 2))
    r = client.post("/api/projects/archive-batch", params={"dir": str(root)},
                    json={"numbers": [2, 1, 99]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    by_number = {row["number"]: row for row in body["results"]}
    assert by_number[1]["ok"] is True
    assert by_number[2]["ok"] is True
    assert by_number[99]["ok"] is False
    assert by_number[99]["code"] == "CHAPTER_NOT_FOUND"
    assert by_number[99]["error"]
    assert body["approvedCount"] == 2
    assert body["failedCount"] == 1

    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    assert all(row["approved"] is True for row in index)


def test_archive_batch_all_success(tmp_path):
    root = make_archive_book(tmp_path, chapters=(1, 2))
    r = client.post("/api/projects/archive-batch", params={"dir": str(root)},
                    json={"numbers": [1, 2]})
    assert r.status_code == 200, r.text
    assert [row["ok"] for row in r.json()["results"]] == [True, True]
    assert r.json()["approvedCount"] == 2


@pytest.mark.parametrize("body", [
    {},
    {"numbers": "1"},
    {"numbers": []},
    {"numbers": [0]},
    {"numbers": [101]},
    {"numbers": [True]},
    {"numbers": [1], "force": "yes"},
])
def test_archive_batch_invalid_numbers_400(tmp_path, body):
    root = make_archive_book(tmp_path)
    r = client.post("/api/projects/archive-batch", params={"dir": str(root)}, json=body)
    assert r.status_code == 400, (body, r.text)


# --------------------------------- 并发保护 ---------------------------------


def test_write_busy_blocks_other_run_allows_same_run(tmp_path, monkeypatch):
    runs.reset()
    root = make_writing_book(tmp_path)
    monkeypatch.setattr(writing, "chat", fake_chat)

    runs.acquire(root, "run-a", 1, "outline")
    r = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)},
                    json={"runId": "run-b"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "WRITE_BUSY"
    assert detail["retryable"] is True
    assert runs.is_busy(root, "run-b") is True
    assert runs.is_busy(root, "run-a") is False

    same = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)},
                       json={"runId": "run-a"})
    assert same.status_code == 200, same.text
    assert runs.current(root) is None  # 请求结束释放

    after = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)},
                        json={"runId": "run-b"})
    assert after.status_code == 200, after.text
    assert after.json()["reused"] is True


def test_different_dirs_do_not_block_each_other(tmp_path, monkeypatch):
    runs.reset()
    root1 = make_writing_book(tmp_path, "书一")
    root2 = make_writing_book(tmp_path, "书二")
    monkeypatch.setattr(writing, "chat", fake_chat)

    runs.acquire(root1, "run-a", 1, "outline")
    r = client.post("/api/projects/chapters/1/outline", params={"dir": str(root2)},
                    json={"runId": "run-b"})
    assert r.status_code == 200, r.text
    assert runs.is_busy(root1, "run-b") is True

    runs.release(root1, "run-a")
    assert runs.is_busy(root1, "run-b") is False
    again = client.post("/api/projects/chapters/1/outline", params={"dir": str(root1)},
                        json={"runId": "run-b"})
    assert again.status_code == 200, again.text


def test_run_expires_after_ttl_and_missing_runid_releases(tmp_path, monkeypatch):
    runs.reset()
    root = make_writing_book(tmp_path)
    monkeypatch.setattr(writing, "chat", fake_chat)

    runs.acquire(root, "run-a", 1, "outline")
    runs._ACTIVE[runs._key(root)]["startedAt"] -= runs.TTL_SECONDS + 1
    assert runs.is_busy(root, "run-b") is False
    runs.acquire(root, "run-b", 1, "outline")  # 过期后放行
    runs.release(root, "run-b")

    # 缺省 runId：请求内生成临时值并释放，不留状态
    r = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert runs.current(root) is None
