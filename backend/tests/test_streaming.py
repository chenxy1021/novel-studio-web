"""流式生成：模型增量 / SSE 事件序列 / 错误也走事件。全部离线。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import blueprint, review, writing
from app.llm import client as llm_client
from app.main import app
from app.store.jsonl import append_jsonl

client = TestClient(app)

LONG = "夜色压下来。" * 200

OUTLINE = {
    "chapter": 1,
    "title": "夜航",
    "beats": ["拍1：老周在码头收船 → 湿透的女人上船 → 她没有影子"],
    "mustInclude": [],
    "mustAvoid": [],
    "openingState": "旧码头",
    "endingState": "河心",
    "pressure": {"deadline": "天亮前", "stake": "错过这一趟", "opponent": "船行会"},
}
OUTLINE_TEXT = (
    "<<<OUTLINE_JSON\n" + json.dumps(OUTLINE, ensure_ascii=False) + "\nOUTLINE_JSON>>>\n"
    "## 3. 节拍\n- 老周收船，女人上船。\n"
)


def make_book(tmp_path: Path) -> Path:
    root = tmp_path / "书"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "流式测试书", "genre": "悬疑", "platform": "generic",
        "targetChapters": 10, "wordsPerChapter": 1000,
        "synopsis": "守渡口的人在雾港载上一个没有影子的女人。",
        "outlineText": "### 第1卷 起（第1-10章）\n老周与阿雾。",
        "worldText": "雾港没有对岸。",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "老周"}], "rules": [], "style": {},
    }, ensure_ascii=False), encoding="utf-8")
    append_jsonl(root / "ledger/foreshadow.jsonl", {
        "id": "fs-test", "name": "断桨", "kind": "main", "plantedChapter": 1,
        "dueChapter": 5, "status": "open", "source": "测试", "at": "",
    })
    return root


def seed_chapter(root: Path) -> None:
    (root / "chapters").mkdir(exist_ok=True)
    (root / "chapters/001-夜航.md").write_text(LONG, encoding="utf-8")
    (root / "chapters/index.json").write_text(json.dumps([{
        "number": 1, "title": "夜航", "file": "chapters/001-夜航.md",
        "chars": 1000, "approved": False,
    }], ensure_ascii=False), encoding="utf-8")


def sse_events(body: str) -> list[dict]:
    return [
        json.loads(line[5:].strip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def streaming_fake(text: str, *, pieces: list[str] | None = None):
    """模拟模型流：先吐几段增量，再返回完整文本。"""
    chunks = pieces if pieces is not None else ["第一段。", "第二段。"]

    def fake(messages, **kwargs):
        on_delta = kwargs.get("on_delta")
        if on_delta:
            for piece in chunks:
                on_delta(piece)
        return {"text": text, "model": "fake", "usage": {"total_tokens": 7}}

    return fake


# ------------------------------- 模型层 -------------------------------


class FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter([line.encode("utf-8") for line in self.lines])


def test_chat_stream_accumulates_deltas(monkeypatch):
    lines = [
        'data: {"model":"m1","choices":[{"delta":{"content":"你"}}]}\n',
        'data: {"choices":[{"delta":{"content":"好"}}]}\n',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":3}}\n',
        "data: [DONE]\n",
    ]
    monkeypatch.setattr(llm_client.urllib.request, "urlopen", lambda req, timeout: FakeResponse(lines))
    got: list[str] = []

    result = llm_client.chat([{"role": "user", "content": "hi"}], on_delta=got.append)
    assert result["text"] == "你好"
    assert result["model"] == "m1"
    assert result["usage"] == {"total_tokens": 3}
    assert "".join(got) == "你好"


def test_chat_stream_empty_is_llm_error(monkeypatch):
    monkeypatch.setattr(
        llm_client.urllib.request, "urlopen",
        lambda req, timeout: FakeResponse(['data: {"choices":[{"delta":{}}]}\n']),
    )

    with pytest.raises(llm_client.LLMError):
        llm_client.chat([{"role": "user", "content": "hi"}], on_delta=lambda _: None)


# ------------------------------- SSE 路由 -------------------------------


def test_outline_stream_emits_stage_delta_done(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(writing, "chat", streaming_fake(OUTLINE_TEXT))

    r = client.post("/api/projects/chapters/1/outline/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")

    events = sse_events(r.text)
    stages = [e["label"] for e in events if e["type"] == "stage"]
    assert stages[0] == "写本章细纲"
    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert deltas == "第一段。第二段。"
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["outline"]["title"] == "夜航"
    assert done["result"]["reused"] is False


def test_prose_stream_emits_text_and_memory_stage(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "0")
    monkeypatch.setattr(writing, "chat", streaming_fake(LONG, pieces=["夜色压下来。"] * 5))
    append_jsonl(root / "ledger/outline.jsonl", {
        "chapter": 1, "title": "夜航", "beats": ["拍1"], "detail": "",
        "source": "ai", "model": "m", "at": "",
    })

    r = client.post("/api/projects/chapters/1/prose/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    assert [e["label"] for e in events if e["type"] == "stage"] == ["写正文", "回写记忆"]
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "夜色压下来。" * 5
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["chars"] >= 300
    assert (root / "chapters/001-夜航.md").is_file()


def test_stream_error_becomes_event(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(writing, "chat", streaming_fake(LONG))
    # 没有细纲 → 领域错误，HTTP 仍是 200（错误在事件里）
    r = client.post("/api/projects/chapters/1/prose/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200
    events = sse_events(r.text)
    err = next(e for e in events if e["type"] == "error")
    assert err["code"] == "NO_OUTLINE_ROW"
    assert err["status"] == 409
    assert not any(e["type"] == "done" for e in events)


def test_rewrite_stream_emits_rewritten_text(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    seed_chapter(root)
    new_text = "改过的正文。" * 200
    monkeypatch.setattr(review, "chat", streaming_fake(new_text, pieces=["改过的正文。"] * 3))

    r = client.post(
        "/api/projects/chapters/1/rewrite/stream",
        params={"dir": str(root)}, json={"skills": ["deai"]},
    )
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "改过的正文。" * 3
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["skills"] == ["deai"]
    assert done["result"]["chars"] >= 300


def test_blueprint_stream_splits_outline_and_world(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    text = (
        "## 全书层\n- 一句话故事核：老周守渡口，等一个不会回来的人。\n"
        "### 第1卷 起（第1-10章）\n"
        "卷内节拍：老周在旧码头收船，夜里载上一个湿透的女人；她没有影子，"
        "老周没有声张，只把船往河心开。\n"
        "### 第2卷 承（第11-20章）\n"
        "卷内节拍：雾港的规矩开始松动，渡口来了查账的人。\n"
        "## 世界观\n## 世界基底\n雾港没有对岸，河上的灯只在夜里亮。\n"
    )
    monkeypatch.setattr(blueprint, "chat", streaming_fake(text, pieces=["## 全书层\n", "雾港没有对岸。\n"]))

    r = client.post("/api/projects/blueprint/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    assert [e["label"] for e in events if e["type"] == "stage"] == ["生成大纲", "拆分世界观"]
    done = next(e for e in events if e["type"] == "done")
    assert "老周守渡口" in done["result"]["outlineText"]
    assert "雾港没有对岸" in done["result"]["worldText"]


# ------------------------- 设定 / 补设定 / 伏笔 -------------------------


def settings_fake(chunks: list[str] | None = None):
    """四路设定调用共用一份 JSON：多出来的键会被按批次忽略。"""
    from app.domain import settings_gen

    payload = json.dumps({
        "characters": [{"name": "阿雾", "aliases": ["雾姐"], "rolePosition": "女主"}],
        "relations": [{"a": "老周", "b": "阿雾", "state": "彼此提防"}],
        "world": [{"name": "雾港", "text": "没有对岸的渡口"}],
        "factions": [{"name": "船行会", "state": "观望"}],
        "locations": [{"name": "旧码头", "state": "冷清"}],
        "items": [{"name": "断桨", "holder": "老周"}],
        "rules": [{"name": "渡船不能空返", "enforce": "契约", "cost": "少一个活人"}],
        "powerSystem": {"name": "摆渡阶", "levels": [{"name": "引路人"}]},
        "society": {"currency": "冥钞"},
        "history": [{"era": "旧朝", "event": "断桥之战", "impact": "两岸断了往来"}],
        "glossary": [{"term": "空返", "meaning": "船不载客回程"}],
        "style": {"pov": "第三人称限知"},
    }, ensure_ascii=False)
    pieces = chunks or ["{\"characters\":[", "{\"name\":\"阿雾\"}]}"]

    def fake(messages, **kwargs):
        on_delta = kwargs.get("on_delta")
        if on_delta:
            for piece in pieces:
                on_delta(piece)
        return {"text": payload, "model": "fake", "usage": {}}

    return fake


def test_settings_stream_emits_stages_deltas_and_result(tmp_path, monkeypatch):
    from app.domain import settings_gen

    root = make_book(tmp_path)
    monkeypatch.setattr(settings_gen, "chat", settings_fake())

    r = client.post("/api/projects/settings/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    stages = [e["label"] for e in events if e["type"] == "stage"]
    assert stages[0] == "四路并行拆设定：人物 / 势力地点 / 物品规则 / 世界纵深"
    assert stages[-1] == "整理设定"
    # 四路并发：完成顺序不固定，但每一路都要有「完成」，各自整块吐出来。
    for label in ("拆人物档案", "拆势力与地点", "拆物品与规则", "拆世界纵深"):
        assert f"{label} · 完成" in stages
    deltas = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "── 拆人物档案 ──" in deltas
    assert "阿雾" in deltas
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["added"]["characters"] == 1
    assert done["result"]["added"]["rules"] == 1
    assert done["result"]["total"] > 0


def test_settings_runs_four_model_calls_in_parallel(tmp_path, monkeypatch):
    """四路必须同时在跑：串行时第一路会等不到其它三路而超时失败。"""
    import threading

    from app.domain import settings_gen

    root = make_book(tmp_path)
    barrier = threading.Barrier(4, timeout=5)
    base = settings_fake()

    def fake(messages, **kwargs):
        barrier.wait()
        return base(messages, **kwargs)

    monkeypatch.setattr(settings_gen, "chat", fake)

    r = client.post("/api/projects/settings/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    done = next(e for e in sse_events(r.text) if e["type"] == "done")
    assert done["result"]["total"] > 0


def test_supplement_stream_reads_chapters_and_emits_done(tmp_path, monkeypatch):
    from app.domain import settings_gen

    root = make_book(tmp_path)
    seed_chapter(root)
    monkeypatch.setattr(settings_gen, "chat", settings_fake())

    r = client.post(
        "/api/projects/settings/supplement/stream",
        params={"dir": str(root)}, json={"recent": 4},
    )
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    assert [e["label"] for e in events if e["type"] == "stage"] == [
        "读最近正文", "补新设定", "整理设定",
    ]
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["chapters"] == [1]


def test_foreshadow_stream_emits_stages_and_rows(tmp_path, monkeypatch):
    from app.domain import foreshadow_gen

    root = make_book(tmp_path)
    lines = "\n".join([
        "名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃",
        "湿脚印|卷内|硬规则·渡船不能空返|2|拍1 甲板上一串水印|9|老周|说明空船载过人|脚印每晚多一个|让水印消失",
    ])
    monkeypatch.setattr(
        foreshadow_gen, "chat", streaming_fake(lines, pieces=["湿脚印|卷内", "|9|老周\n"]),
    )

    r = client.post("/api/projects/foreshadow/generate/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    assert [e["label"] for e in events if e["type"] == "stage"] == ["铺伏笔网", "整理种子"]
    assert "湿脚印" in "".join(e["text"] for e in events if e["type"] == "delta")
    done = next(e for e in events if e["type"] == "done")
    assert done["result"]["count"] == 1


def test_settings_retries_once_when_model_returns_bad_json(tmp_path, monkeypatch):
    """模型偶尔先回一段解释再回 JSON：重试一次，别把整轮判死。"""
    from app.domain import settings_gen

    root = make_book(tmp_path)
    calls = {"n": 0}

    def flaky(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"text": "好的，我来拆设定。", "model": "fake", "usage": {}}
        return settings_fake()(messages, **kwargs)

    monkeypatch.setattr(settings_gen, "chat", flaky)

    r = client.post("/api/projects/settings/stream", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    events = sse_events(r.text)
    stages = [e["label"] for e in events if e["type"] == "stage"]
    assert any("格式不对，重试" in label for label in stages)
    assert next(e for e in events if e["type"] == "done")["result"]["total"] > 0
