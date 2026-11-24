"""分步写作：细纲复用、正文错误码、文风注入、focus、/generate 兼容。全部离线。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import memory_gen, writing
from app.main import app
from app.store.jsonl import append_jsonl

client = TestClient(app)

LONG = "夜色压下来。" * 200  # 1000 个汉字
SHORT = "短句。" * 10

OUTLINE = {
    "chapter": 1,
    "title": "夜航",
    "beats": ["拍1：老周在码头收船 → 一个湿透的女人上船 → 她没有影子"],
    "mustInclude": ["断桨"],
    "mustAvoid": [],
    "openingState": "旧码头",
    "endingState": "河心",
    "pressure": {"deadline": "天亮前", "stake": "错过这一趟", "opponent": "船行会"},
}
OUTLINE_TEXT = (
    "<<<OUTLINE_JSON\n" + json.dumps(OUTLINE, ensure_ascii=False) + "\nOUTLINE_JSON>>>\n"
    "## 3. 节拍\n- 老周收船，女人上船。\n"
)


def seed_foreshadow(root: Path, name: str = "断桨") -> None:
    append_jsonl(root / "ledger/foreshadow.jsonl", {
        "id": "fs-test", "name": name, "kind": "main", "plantedChapter": 1,
        "dueChapter": 5, "status": "open", "source": "测试", "at": "",
    })


def make_book(
    tmp_path: Path,
    *,
    style: dict | None = None,
    outline_text: str | None = None,
    foreshadow: bool = True,
) -> Path:
    root = tmp_path / "书"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "分步测试书",
        "genre": "悬疑",
        "platform": "generic",
        "targetChapters": 10,
        "wordsPerChapter": 1000,
        "outlineText": "### 第1卷 起（第1-10章）\n老周与阿雾。" if outline_text is None else outline_text,
        "worldText": "雾港没有对岸。",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "老周", "want": "守住渡口"}],
        "rules": [],
        "style": style or {},
    }, ensure_ascii=False), encoding="utf-8")
    if foreshadow:
        seed_foreshadow(root)
    return root


def fake_chat_factory(calls: list[list[dict]], *, prose: str = LONG):
    def fake(messages, **kwargs):
        calls.append(messages)
        if "章节设计编辑" in messages[0]["content"]:
            return {"text": OUTLINE_TEXT, "model": "m-outline", "usage": {}}
        return {"text": prose, "model": "m-prose", "usage": {}}
    return fake


def user_text(messages: list[dict]) -> str:
    return next(m["content"] for m in messages if m["role"] == "user")


def test_outline_without_book_outline_400(tmp_path):
    root = make_book(tmp_path, outline_text="")
    r = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)}, json={})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "NO_OUTLINE"


def test_outline_reused_without_model_call(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    calls: list[list[dict]] = []
    monkeypatch.setattr(writing, "chat", fake_chat_factory(calls))

    first = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)}, json={})
    assert first.status_code == 200, first.text
    assert first.json()["reused"] is False
    assert first.json()["outline"]["title"] == "夜航"
    assert len(calls) == 1

    second = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)}, json={})
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["outline"]["title"] == "夜航"
    assert len(calls) == 1  # 复用不调模型

    forced = client.post("/api/projects/chapters/1/outline",
                         params={"dir": str(root)}, json={"force": True})
    assert forced.status_code == 200, forced.text
    assert forced.json()["reused"] is False
    assert len(calls) == 2


BATCH_OUTLINE = {
    "from": 1,
    "to": 3,
    "spine": "老周先验船，再失去渡口，最后被迫出航。",
    "chapters": [
        {
            "chapter": 1, "title": "夜航",
            "beats": ["拍1：老周在旧码头收船 → 湿透的女人上船 → 她没有影子"],
            "mustInclude": ["断桨"], "mustAvoid": [],
            "openingState": "旧码头", "endingState": "河心",
            "pressure": {"deadline": "天亮前", "stake": "错过这一趟", "opponent": "船行会"},
        },
        {
            "chapter": 2, "title": "无影",
            "beats": ["拍1：河心起雾 → 老周发现她不上岸 → 渡口规矩被触发"],
            "mustInclude": [], "mustAvoid": ["解释影子"],
            "openingState": "河心", "endingState": "渡口账房",
            "pressure": {"deadline": "下一次点名", "stake": "丢船", "opponent": "船行会"},
        },
        {
            "chapter": 3, "title": "点名",
            "beats": ["拍1：账房点名 → 少一个活人 → 老周被推到台前"],
            "mustInclude": [], "mustAvoid": [],
            "openingState": "渡口账房", "endingState": "旧码头",
            "pressure": {"deadline": "天亮", "stake": "被逐出渡口", "opponent": "账房"},
        },
    ],
}
BATCH_TEXT = json.dumps(BATCH_OUTLINE, ensure_ascii=False)


def test_batch_outline_one_call_for_whole_batch(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    calls: list[list[dict]] = []

    def fake(messages, **kwargs):
        calls.append(messages)
        return {"text": BATCH_TEXT, "model": "m-batch", "usage": {"total_tokens": 120}}

    monkeypatch.setattr(writing, "chat", fake)
    r = client.post("/api/projects/outlines/batch", params={"dir": str(root)},
                    json={"from": 1, "to": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reused"] is False
    assert [o["chapter"] for o in body["outlines"]] == [1, 2, 3]
    assert [o["title"] for o in body["outlines"]] == ["夜航", "无影", "点名"]
    assert body["outlines"][0]["endingState"] == "河心"
    assert body["outlines"][1]["openingState"] == "河心"
    assert body["outlines"][0]["batchFrom"] == 1
    assert body["outlines"][0]["batchTo"] == 3
    assert body["spine"].startswith("老周先验船")
    assert len(calls) == 1  # 一批只调一次模型

    prompt = user_text(calls[0])
    assert "【本批】第 1–3 章（共 3 章）" in prompt
    assert "本批伏笔日程" in prompt
    assert '"chapters"' in prompt

    rows = [json.loads(line) for line in
            (root / "ledger/outline.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["chapter"] for row in rows] == [1, 2, 3]
    assert all(row["batchSpine"] == BATCH_OUTLINE["spine"] for row in rows)

    # 整批已排好：再点一次直接复用，不再调模型。
    again = client.post("/api/projects/outlines/batch", params={"dir": str(root)},
                        json={"from": 1, "to": 3})
    assert again.status_code == 200, again.text
    assert again.json()["reused"] is True
    assert len(calls) == 1


def test_batch_outline_missing_chapter_502(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    partial = {"from": 1, "to": 2, "spine": "",
               "chapters": [{"chapter": 1, "title": "夜航", "beats": ["拍1：上船"]}]}

    monkeypatch.setattr(writing, "chat", lambda m, **k: {
        "text": json.dumps(partial, ensure_ascii=False), "model": "m", "usage": {},
    })
    r = client.post("/api/projects/outlines/batch", params={"dir": str(root)},
                    json={"from": 1, "to": 2})
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["code"] == "LLM_ERROR"
    assert not (root / "ledger/outline.jsonl").exists()


def test_batch_outline_then_prose_uses_its_chapter_row(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    calls: list[list[dict]] = []

    def fake(messages, **kwargs):
        calls.append(messages)
        if "分批细纲编辑" in messages[0]["content"]:
            return {"text": BATCH_TEXT, "model": "m-batch", "usage": {}}
        return {"text": LONG, "model": "m-prose", "usage": {}}

    monkeypatch.setattr(writing, "chat", fake)
    assert client.post("/api/projects/outlines/batch", params={"dir": str(root)},
                       json={"from": 1, "to": 3}).status_code == 200

    r = client.post("/api/projects/chapters/2/prose", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert r.json()["chapter"]["title"] == "无影"
    prose_prompt = user_text(calls[-1])
    assert "河心起雾" in prose_prompt  # 用的是第 2 章自己的节拍
    assert "老周先验船" not in prose_prompt


def test_prose_without_outline_row_409(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/chapters/1/prose", params={"dir": str(root)}, json={})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "NO_OUTLINE_ROW"


def test_prose_existing_text_409(tmp_path):
    root = make_book(tmp_path)
    (root / "chapters").mkdir()
    body = "chapters/001-夜航.md"
    (root / body).write_text(LONG, encoding="utf-8")
    (root / "chapters/index.json").write_text(json.dumps([{
        "number": 1, "title": "夜航", "file": body, "chars": 1000, "approved": False,
    }], ensure_ascii=False), encoding="utf-8")

    r = client.post("/api/projects/chapters/1/prose", params={"dir": str(root)}, json={})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "CHAPTER_EXISTS"


def test_prose_without_foreshadow_409(tmp_path, monkeypatch):
    root = make_book(tmp_path, foreshadow=False)
    append_jsonl(root / "ledger/outline.jsonl", {
        "chapter": 1, "title": "夜航", "beats": ["拍1：老周收船"], "detail": "",
        "source": "ai", "model": "m", "at": "",
    })
    calls: list[list[dict]] = []
    monkeypatch.setattr(writing, "chat", fake_chat_factory(calls))

    r = client.post("/api/projects/chapters/1/prose", params={"dir": str(root)}, json={})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "NO_FORESHADOW"
    assert not calls  # 没伏笔就不该调模型
    assert not (root / "chapters/001-夜航.md").exists()


def test_prose_too_short_502_leaves_no_chapter(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    append_jsonl(root / "ledger/outline.jsonl", {
        "chapter": 1, "title": "夜航", "beats": ["拍1：老周收船"], "detail": "",
        "source": "ai", "model": "m", "at": "",
    })
    calls: list[list[dict]] = []
    monkeypatch.setattr(writing, "chat", fake_chat_factory(calls, prose=SHORT))

    r = client.post("/api/projects/chapters/1/prose", params={"dir": str(root)}, json={})
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["code"] == "PROSE_TOO_SHORT"
    assert not (root / "chapters/001-夜航.md").exists()
    index_file = root / "chapters/index.json"
    assert not index_file.exists() or json.loads(index_file.read_text(encoding="utf-8")) == []


def test_style_override_reaches_both_prompts_and_wins(tmp_path, monkeypatch):
    root = make_book(tmp_path, style={"rhythm": "缓", "banned": ["他很难过"]})
    calls: list[list[dict]] = []
    monkeypatch.setattr(writing, "chat", fake_chat_factory(calls))

    override = {"rhythm": "紧", "banned": ["空气仿佛凝固"]}
    outline = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)},
                          json={"styleOverride": override})
    assert outline.status_code == 200, outline.text
    outline_prompt = user_text(calls[-1])
    assert "节奏：紧" in outline_prompt
    assert "空气仿佛凝固" in outline_prompt
    assert "节奏：缓" not in outline_prompt
    assert "他很难过" not in outline_prompt
    assert outline.json()["styleApplied"]["source"] == "book+override"
    assert outline.json()["styleApplied"]["effective"]["rhythm"] == "紧"

    prose = client.post("/api/projects/chapters/1/prose", params={"dir": str(root)},
                        json={"styleOverride": override})
    assert prose.status_code == 200, prose.text
    prose_prompt = user_text(calls[-1])
    assert "节奏：紧" in prose_prompt
    assert "空气仿佛凝固" in prose_prompt
    assert "节奏：缓" not in prose_prompt
    assert prose.json()["styleApplied"]["source"] == "book+override"


def test_focus_block_at_top_and_capped_at_five(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    calls: list[list[dict]] = []
    monkeypatch.setattr(writing, "chat", fake_chat_factory(calls))
    focus = [{"type": "foreshadow", "key": f"fs-{i}", "label": f"强调{i}"} for i in range(1, 7)]

    r = client.post("/api/projects/chapters/1/outline", params={"dir": str(root)},
                    json={"focus": focus})
    assert r.status_code == 200, r.text
    prompt = user_text(calls[-1])
    assert prompt.startswith("【本章额外强调")
    for i in range(1, 6):
        assert f"强调{i}" in prompt
    assert "强调6" not in prompt
    assert prompt.index("强调1") < prompt.index("强调2")


def test_generate_compat_endpoint_still_works(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(writing, "chat", fake_chat_factory([]))

    r = client.post("/api/projects/chapters/1/generate", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapter"]["number"] == 1
    assert body["outline"]["title"] == "夜航"
    assert body["chars"] >= 300
    assert (root / "chapters/001-夜航.md").is_file()
    assert "styleApplied" not in body  # 兼容包装保持旧响应结构


# --------------------------- 正文落盘后自动回写记忆 ---------------------------

CHAPTER_MEMORY = json.dumps({
    "summary": "老周在旧码头收船，一个湿透的女人上船；她没有影子，老周没有声张。" * 3,
    "characters": ["老周", "阿雾"],
    "places": ["旧码头"],
    "events": ["老周收船", "女人上船"],
    "storyTime": "第1天·夜",
    "knows": [],
    "relations": [],
    "timeline": [{
        "storyTime": "第1天·夜", "place": "旧码头", "characters": ["老周"],
        "event": "女人上船", "kind": "event", "revealChapter": None,
    }],
}, ensure_ascii=False)

VOLUME_MEMORY = json.dumps({
    "summary": "第一卷：老周在雾港守渡口，夜里载上一个没有影子的女人，旧码头的规矩开始松动。" * 3,
    "dims": {"mainline": "女人上船", "threads": "", "relations": "", "knowledge": "", "carryover": "", "drift": ""},
}, ensure_ascii=False)


def memory_chat(messages, **kwargs):
    system = messages[0]["content"]
    text = VOLUME_MEMORY if "卷记忆编辑" in system else CHAPTER_MEMORY
    return {"text": text, "model": "m-mem", "usage": {"total_tokens": 42}}


def test_prose_auto_writes_chapter_and_volume_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "1")
    root = make_book(tmp_path)
    append_jsonl(root / "ledger/volumes.json", {"volumes": [{"title": "第一卷 起", "from": 1, "to": 1}]})
    monkeypatch.setattr(writing, "chat", fake_chat_factory([]))
    monkeypatch.setattr(memory_gen, "chat", memory_chat)

    r = client.post("/api/projects/chapters/1/generate", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["memory"]["ok"] is True
    assert body["memory"]["chapter"]["chapter"] == 1
    assert body["memory"]["chapter"]["timelineCount"] == 1
    assert body["memory"]["volume"]["volume"] == 1

    rows = [json.loads(line) for line in (root / "ledger/memory.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["kind"] for r in rows} == {"chapter", "volume"}
    assert (root / "ledger/timeline.jsonl").is_file()
    usage = [json.loads(line) for line in (root / "metrics/usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"memory", "memory-volume"} <= {u["kind"] for u in usage}


def test_prose_memory_failure_does_not_fail_chapter(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "1")
    root = make_book(tmp_path)
    monkeypatch.setattr(writing, "chat", fake_chat_factory([]))
    monkeypatch.setattr(memory_gen, "chat", lambda m, **k: {"text": "这不是 JSON", "model": "m", "usage": {}})

    r = client.post("/api/projects/chapters/1/generate", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["memory"]["ok"] is False and body["memory"]["error"]
    assert (root / "chapters/001-夜航.md").is_file()
    assert not (root / "ledger/memory.jsonl").exists()
