"""切片 3：章记忆 / 卷摘要 / 时间线 / 记忆查询接口。全部离线（monkeypatch chat）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import create, memory, memory_gen
from app.llm import LLMError
from app.main import app
from app.store import add_to_index, append_jsonl, project_path, read_jsonl
from app.store.chapter import count_chars, write_chapter

client = TestClient(app)

MEMORY_PATH = memory.MEMORY_FILE
TIMELINE_PATH = memory_gen.TIMELINE_FILE
VOLUMES_PATH = "ledger/volumes.json"


def _book(tmp_path: Path, monkeypatch, *, chapters: int = 3) -> Path:
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    info = create.create_book(title="记忆测试书", genre="悬疑", target_chapters=20)
    root = Path(info["dir"])
    for n in range(1, chapters + 1):
        text = f"第{n}章正文，主角在打铁铺发现线索，决定继续追查下去。" * 4
        _, rel = write_chapter(root, n, f"第{n}章", text)
        add_to_index(root, {
            "number": n, "title": f"第{n}章", "file": rel,
            "chars": count_chars(text), "approved": False,
        })
    return root


def _chapter_json(n: int, *, summary: str | None = None, timeline: bool = True) -> str:
    data = {
        "summary": summary or (
            f"第{n}章，沈默在打铁铺接下修刀委托，阿枝从刀鞘夹层里摸出铜钥匙，"
            "认出这是父亲的遗物。两人因为这把钥匙从信任转向戒备，欠债期限只剩两天。"
        ),
        "characters": ["沈默", "阿枝"],
        "places": ["打铁铺"],
        "events": [f"沈默接下修刀委托{n}", f"阿枝发现刀鞘夹层{n}"],
        "storyTime": f"第{n}天",
        "knows": [{"who": "阿枝", "learned": "铜钥匙是父亲的遗物"}],
        "relations": [{"a": "沈默", "b": "阿枝", "change": "信任→戒备"}],
    }
    if timeline:
        data["timeline"] = [
            {"storyTime": f"第{n}天", "place": "打铁铺", "characters": ["沈默"],
             "event": f"沈默接下修刀委托{n}", "kind": "event", "revealChapter": None},
            {"storyTime": f"第{n}天", "place": "打铁铺", "characters": ["阿枝"],
             "event": f"阿枝发现铜钥匙{n}", "kind": "foreshadow-plant", "revealChapter": 5},
        ]
    return json.dumps(data, ensure_ascii=False)


def _volume_json() -> str:
    return json.dumps({
        "summary": "第一卷里，沈默守着打铁铺接下修刀委托，阿枝从刀鞘夹层发现父亲的铜钥匙。"
                   "两人因钥匙来源互相隐瞒，关系从信任转为戒备；卷末沈默留铺，阿枝带钥匙离开，欠债期限逼近。",
        "dims": {
            "mainline": "沈默接下委托，追查铜钥匙来源。",
            "threads": "阿枝身世线被推进。",
            "relations": "沈默与阿枝从信任转为戒备。",
            "knowledge": "读者知道钥匙是遗物，沈默还不知道。",
            "carryover": "铜钥匙与两天的欠债期限必须带进下一卷。",
            "drift": "",
        },
    }, ensure_ascii=False)


def _fake_chat(text_fn):
    def fake(messages, **kwargs):
        return {"text": text_fn(messages, kwargs), "model": "fake-model", "usage": {}}
    return fake


def _user_of(messages: list[dict]) -> str:
    return next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")


def test_chapter_memory_writes_rows_skips_and_force(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    replies = iter([_chapter_json(1, summary="第一次生成的摘要。"), _chapter_json(1, summary="第二次生成的摘要。")])
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: next(replies)))

    result = memory_gen.generate_chapter_memory(root, 1)
    assert result["chapter"] == 1
    assert result["timelineCount"] == 2
    assert result["characters"] == ["沈默", "阿枝"]

    rows = read_jsonl(project_path(root, MEMORY_PATH))
    chapter_rows = [r for r in rows if r.get("kind") == "chapter"]
    assert len(chapter_rows) == 1
    assert chapter_rows[0]["chapter"] == 1
    assert chapter_rows[0]["summary"] == "第一次生成的摘要。"
    assert chapter_rows[0]["places"] == ["打铁铺"]
    assert chapter_rows[0]["knows"] == [{"who": "阿枝", "learned": "铜钥匙是父亲的遗物"}]

    timeline = read_jsonl(project_path(root, TIMELINE_PATH))
    assert len(timeline) == 2
    assert [t["chapter"] for t in timeline] == [1, 1]
    assert timeline[1]["kind"] == "foreshadow-plant"
    assert timeline[1]["revealChapter"] == 5
    assert timeline[0]["revealChapter"] is None

    extra = memory_gen.generate_chapter_memory(root, 1)
    assert extra == {"skipped": True, "chapter": 1}
    assert len(read_jsonl(project_path(root, MEMORY_PATH))) == 1

    forced = memory_gen.generate_chapter_memory(root, 1, force=True)
    assert forced["summary"] == "第二次生成的摘要。"
    latest = memory.load_memory_rows(root)["byChapter"][1]
    assert latest["summary"] == "第二次生成的摘要。"


def test_flashback_chapter_and_events_are_marked(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    data = json.loads(_chapter_json(1))
    data["storyTime"] = "十年前 · 秋"
    data["isFlashback"] = True
    data["timeline"][0]["flashback"] = True
    data["timeline"][1]["flashback"] = "false"  # 模型写成字符串也不能当 true
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: json.dumps(data, ensure_ascii=False)))

    result = memory_gen.generate_chapter_memory(root, 1)
    assert result["isFlashback"] is True

    chapter_rows = memory.load_memory_rows(root)["byChapter"]
    assert chapter_rows[1]["isFlashback"] is True
    assert chapter_rows[1]["storyTime"] == "十年前 · 秋"

    timeline = read_jsonl(project_path(root, TIMELINE_PATH))
    assert timeline[0]["flashback"] is True
    assert timeline[1]["flashback"] is False

    overview = memory_gen.memory_overview(root)
    assert overview["chapters"][0]["isFlashback"] is True
    assert overview["timeline"][0]["flashback"] is True
    assert overview["timeline"][1]["flashback"] is False


def test_timeline_falls_back_to_one_event(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    summary = "模型忘了时间线，但仍给出了可用的摘要。" * 4
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: _chapter_json(1, summary=summary, timeline=False)))

    result = memory_gen.generate_chapter_memory(root, 1)
    assert result["timelineCount"] == 1
    timeline = read_jsonl(project_path(root, TIMELINE_PATH))
    assert len(timeline) == 1
    assert timeline[0]["kind"] == "event"
    assert timeline[0]["event"] == result["summary"][:80]
    assert timeline[0]["revealChapter"] is None


def test_volume_memory_generates_and_skips(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    append_jsonl(project_path(root, VOLUMES_PATH), {
        "volumes": [{"title": "第一卷 起", "from": 1, "to": 3}],
    })
    calls: list[str] = []

    def respond(messages, _kwargs):
        system = messages[0]["content"]
        calls.append(system)
        if "卷记忆编辑" in system:
            return _volume_json()
        user = _user_of(messages)
        n = 1 if "第 1 章" in user else 2
        return _chapter_json(n)

    monkeypatch.setattr(memory_gen, "chat", _fake_chat(respond))
    memory_gen.generate_chapter_memory(root, 1)
    memory_gen.generate_chapter_memory(root, 2)

    result = memory_gen.generate_volume_memory(root, 1)
    assert result["volume"] == 1
    assert result["from"] == 1 and result["to"] == 3
    assert result["dims"]["mainline"].startswith("沈默")
    assert result["summary"]

    rows = [r for r in read_jsonl(project_path(root, MEMORY_PATH)) if r.get("kind") == "volume"]
    assert len(rows) == 1
    assert rows[0]["volume"] == 1
    assert set(rows[0]["dims"]) == set(memory_gen.VOLUME_DIMS)

    before = len(calls)
    skipped = memory_gen.generate_volume_memory(root, 1)
    assert skipped["skipped"] is True
    assert len(calls) == before  # 跳过不调模型


def test_get_memory_coverage_counts_written_and_missing(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda messages, _kw: _chapter_json(
        1 if "第 1 章" in _user_of(messages) else 2,
    )))
    memory_gen.generate_chapter_memory(root, 1)
    memory_gen.generate_chapter_memory(root, 2)
    append_jsonl(project_path(root, VOLUMES_PATH), {
        "volumes": [{"title": "第一卷 起", "from": 1, "to": 3}],
    })
    memory.append_memory(root, {
        "kind": "volume", "volume": 1, "title": "第一卷 起", "from": 1, "to": 3,
        "summary": "本卷总述。", "dims": {"mainline": "主线"},
    })

    r = client.get("/api/projects/memory", params={"dir": str(root)})
    assert r.status_code == 200, r.text
    body = r.json()
    coverage = body["coverage"]
    assert coverage["chaptersWithText"] == 3
    assert coverage["chaptersWithMemory"] == 2
    assert coverage["missing"] == [3]
    assert coverage["volumes"] == 1
    assert coverage["volumesWithMemory"] == 1
    assert body["volumes"] == [{
        "volume": 1, "title": "第一卷 起", "from": 1, "to": 3,
        "summary": "本卷总述。", "dims": {"mainline": "主线"},
    }]

    assert [c["chapter"] for c in body["chapters"]] == [1, 2, 3]
    assert body["chapters"][2]["summary"] == ""
    assert body["chapters"][0]["summary"].startswith("第1章")
    assert len(body["timeline"]) == 4
    assert body["relations"] == [{"a": "沈默", "b": "阿枝", "state": "信任→戒备", "chapter": 2}]
    assert body["characters"][0]["name"] in {"沈默", "阿枝"}
    assert all(set(c) == {"name", "state", "chapter"} for c in body["characters"])


def test_invalid_json_raises_and_writes_nothing(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: "这不是 JSON，只是一段解释。"))

    with pytest.raises(LLMError):
        memory_gen.generate_chapter_memory(root, 1)
    assert read_jsonl(project_path(root, MEMORY_PATH)) == []
    assert read_jsonl(project_path(root, TIMELINE_PATH)) == []


def test_batch_continues_after_one_failure(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)

    def respond(messages, _kw):
        user = _user_of(messages)
        if "第 2 章" in user:
            return "格式坏掉了"
        return _chapter_json(1 if "第 1 章" in user else 3)

    monkeypatch.setattr(memory_gen, "chat", _fake_chat(respond))
    result = memory_gen.generate_memory_batch(root, 1, 3)

    assert result["total"] == 3
    assert result["ok"] == 2
    assert result["failed"] == [{"chapter": 2, "error": result["failed"][0]["error"]}]
    assert result["timelineCount"] == 4
    assert set(memory.load_memory_rows(root)["byChapter"]) == {1, 3}


def test_recall_endpoint_returns_hits(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: _chapter_json(1)))
    memory_gen.generate_chapter_memory(root, 1)

    r = client.get("/api/projects/memory/recall", params={"dir": str(root), "q": "铜钥匙"})
    assert r.status_code == 200, r.text
    hits = r.json()["hits"]
    assert hits
    assert {"chapter", "title", "text", "score"} <= set(hits[0])
    assert any(h["chapter"] == 1 for h in hits)


def test_memory_overview_lists_structural_volumes_without_summary(tmp_path, monkeypatch):
    """卷摘要还没生成时也要出现在列表里，前端才知道可以补。"""
    root = _book(tmp_path, monkeypatch)
    append_jsonl(project_path(root, VOLUMES_PATH), {
        "volumes": [
            {"title": "第一卷 起", "from": 1, "to": 2},
            {"title": "第二卷 承", "from": 3, "to": 3},
        ],
    })

    body = client.get("/api/projects/memory", params={"dir": str(root)}).json()
    assert [v["volume"] for v in body["volumes"]] == [1, 2]
    assert [v["title"] for v in body["volumes"]] == ["第一卷 起", "第二卷 承"]
    assert body["volumes"][1]["summary"] == ""
    assert body["coverage"]["volumes"] == 2
    assert body["coverage"]["volumesWithMemory"] == 0


def test_auto_write_back_skips_when_disabled(tmp_path, monkeypatch):
    """默认（conftest 关掉自动回写）不调模型，只回报 skipped。"""
    root = _book(tmp_path, monkeypatch)
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "0")
    assert memory_gen.auto_write_back(root, 1)["skipped"] is True
    assert read_jsonl(project_path(root, MEMORY_PATH)) == []


def test_auto_write_back_swallows_model_errors(tmp_path, monkeypatch):
    root = _book(tmp_path, monkeypatch)
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "1")
    monkeypatch.setattr(memory_gen, "chat", _fake_chat(lambda *_: "坏掉的回包"))

    result = memory_gen.auto_write_back(root, 1)
    assert result["ok"] is False and result["error"]
    assert read_jsonl(project_path(root, MEMORY_PATH)) == []


def test_chapter_memory_keeps_character_states(tmp_path, monkeypatch):
    """章记忆要把「谁死了 / 谁走了」留下来：存档回写时才有一手依据。"""
    root = _book(tmp_path, monkeypatch)
    data = json.loads(_chapter_json(1))
    data["characterStates"] = [{"who": "阿枝", "status": "死亡", "note": "坠崖"}]
    seen: dict[str, str] = {}

    def fake(messages, **kwargs):
        seen["user"] = _user_of(messages)
        return {"text": json.dumps(data, ensure_ascii=False), "model": "fake-model", "usage": {}}

    monkeypatch.setattr(memory_gen, "chat", fake)
    memory_gen.generate_chapter_memory(root, 1)

    assert "characterStates" in seen["user"]
    assert "死亡" in seen["user"]
    row = memory.load_memory_rows(root)["byChapter"][1]
    assert row["characterStates"] == [{"who": "阿枝", "status": "死亡", "note": "坠崖"}]
