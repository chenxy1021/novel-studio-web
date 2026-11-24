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


CHECKLIST_MARK = "【判定清单（只判这些，id 原样返回，不要增删）】\n"


def prompt_items(prompt: str) -> list[dict]:
    """从复检提示词里取回清单项，假模型据此逐项回答（和真模型看到的完全一样）。"""
    for mark in (CHECKLIST_MARK, "【清单】\n"):
        if mark in prompt:
            start = prompt.index(mark) + len(mark)
            items, _ = json.JSONDecoder().raw_decode(prompt[start:])
            return items
    return []


def ai_reply(messages, *, fails=None, suggestions=None, preface="", wrap=False) -> dict:
    """假模型回包：默认清单全过；fails 里指定的项判不过。"""
    fails = fails or {}
    checks = []
    for item in prompt_items(messages[-1]["content"]):
        row = {"id": item["id"], "pass": True, "quote": "", "note": "", "hint": ""}
        if item["id"] in fails:
            row.update(fails[item["id"]])
            row["pass"] = False
        checks.append(row)
    text = preface + json.dumps(
        {"checks": checks, "suggestions": suggestions or []}, ensure_ascii=False,
    )
    if wrap:
        text = "下面是审稿结果：\n```json\n" + text[:-1] + ",}\n```"
    return {"text": text, "model": "test-model", "usage": {"total_tokens": 5}}


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


def test_reject_rolls_back_derived_settings_and_restore_brings_them_back(tmp_path):
    """退稿要把这一章并进 bible 的位置/转手/状态退回去；恢复废章时再回来。"""
    from app.domain.memory import load_memory_rows

    root = make_book(tmp_path)
    body2 = "chapters/002-第二天.md"
    (root / body2).write_text("他推开门，塔顶的灯已经灭了。" * 20, encoding="utf-8")
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    index.append({
        "number": 2, "title": "第二天", "file": body2, "chars": 200,
        "summary": "第二天灯灭了。", "characters": ["季恒"], "approved": False,
        "chapterVerdict": "pass", "verdict": "良", "fixReasons": [], "dialogueRatio": 0.1,
    })
    (root / "chapters/index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    (root / "ledger/memory.jsonl").write_text("\n".join([
        json.dumps({
            "kind": "chapter", "chapter": 1, "title": "第一段广播", "summary": "季恒在塔下修塔。",
            "events": ["塔下开工"], "items": [{"name": "扳手", "holder": "老周", "state": "完好"}],
        }, ensure_ascii=False),
        json.dumps({
            "kind": "chapter", "chapter": 2, "title": "第二天", "summary": "季恒爬上塔顶，灯灭了。",
            "events": ["灯灭"], "moves": [{"who": "季恒", "to": "塔顶"}],
            "items": [{"name": "扳手", "holder": "季恒", "state": "断了"}],
            "factionStates": [{"name": "守夜队", "state": "戒严"}],
            "placeStates": [{"name": "塔顶", "state": "熄灯", "occupied": "守夜队"}],
        }, ensure_ascii=False),
        json.dumps({
            "kind": "volume", "volume": 1, "title": "第一卷", "from": 1, "to": 2,
            "summary": "季恒修塔，灯灭。",
        }, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    (root / "ledger/volumes.json").write_text(json.dumps({
        "volumes": [{"title": "第一卷", "from": 1, "to": 2}],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "ledger/timeline.jsonl").write_text("\n".join([
        json.dumps({"chapter": 1, "event": "塔下开工", "at": "2026-01-01T00:00:00Z"}, ensure_ascii=False),
        json.dumps({"chapter": 2, "event": "灯灭", "at": "2026-01-01T00:01:00Z"}, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{
            "name": "季恒", "want": "把塔修好", "location": "塔顶", "locationAt": 2,
            "locationHistory": [{"chapter": 1, "place": "塔下"}, {"chapter": 2, "place": "塔顶"}],
        }],
        "items": [{
            "name": "扳手", "holder": "季恒", "holderAt": 2, "state": "断了", "stateAt": 2,
            "transferLog": [
                {"chapter": 1, "from": "", "to": "老周"},
                {"chapter": 2, "from": "老周", "to": "季恒"},
            ],
        }],
        "factions": [{"name": "守夜队", "state": "戒严", "stateAt": 2}],
        "locations": [{"name": "塔顶", "state": "熄灯", "stateAt": 2, "occupied": "守夜队"}],
    }, ensure_ascii=False), encoding="utf-8")

    r = client.post("/api/projects/chapters/2/reject", params={"dir": str(root)}, json={"reason": "重写"})
    assert r.status_code == 200, r.text
    draft = r.json()["draftFile"]

    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    assert bible["characters"][0]["location"] == "塔下"
    assert bible["characters"][0]["locationAt"] == 1
    assert all(m["chapter"] != 2 for m in bible["characters"][0]["locationHistory"])
    assert bible["items"][0]["holder"] == "老周"
    assert bible["items"][0]["holderAt"] == 1
    assert bible["items"][0]["state"] == "完好"
    assert bible["factions"][0]["stateAt"] != 2
    assert bible["locations"][0]["stateAt"] != 2

    # 章记忆还在文件里，但按正文索引过滤后不再生效；覆盖它的卷摘要标为失效
    assert 2 not in load_memory_rows(root)["byChapter"]
    assert load_memory_rows(root)["volumes"] == []

    r = client.post("/api/projects/discarded/restore", params={"dir": str(root)}, json={"draftFile": draft})
    assert r.status_code == 200, r.text
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    assert bible["characters"][0]["location"] == "塔顶"
    assert bible["items"][0]["holder"] == "季恒"
    assert 2 in load_memory_rows(root)["byChapter"]
    assert load_memory_rows(root)["volumes"][0]["summary"] == "季恒修塔，灯灭。"


def test_save_chapter_text_unapproves(tmp_path):
    root = make_book(tmp_path)
    client.post("/api/projects/chapters/1/archive", params={"dir": str(root)}, json={})
    r = client.put("/api/projects/chapters/1", params={"dir": str(root)},
                   json={"text": LONG + "补一句。"})
    assert r.status_code == 200, r.text
    assert r.json()["chapter"]["approved"] is False
    assert "补一句" in (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8")


def test_check_results_persist_and_mark_stale(tmp_path):
    """体检结果落 ledger/checks.jsonl：刷新后还能看到；正文改过就标 stale。"""
    root = make_book(tmp_path)
    single = client.get("/api/projects/chapters/1/check", params={"dir": str(root)}).json()
    assert single["pass"] is True

    rows = client.get("/api/projects/checks", params={"dir": str(root)}).json()["rows"]
    assert len(rows) == 1
    assert rows[0]["chapter"] == 1 and rows[0]["stale"] is False
    assert rows[0]["result"]["checkedAt"] == single["checkedAt"]

    # 按批体检写的是同一份缓存，结果形状一致
    batch = client.post("/api/projects/check-batch", params={"dir": str(root)},
                        json={"from": 1, "to": 1}).json()
    rows = client.get("/api/projects/checks", params={"dir": str(root)}).json()["rows"]
    assert rows[0]["result"]["pass"] == batch["chapters"][0]["pass"]

    (root / "chapters/001-第一段广播.md").write_text(LONG + "补一句。", encoding="utf-8")
    rows = client.get("/api/projects/checks", params={"dir": str(root)}).json()["rows"]
    assert rows[0]["stale"] is True


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


PARA_TEXT = (
    "他把最后一颗螺丝拧紧，塔顶的红灯亮起来。" * 40
    + "\n\n"
    + "她站在塔下，抬头看着那盏灯。" * 40
    + "\n\n"
    + "风从海面吹过来，灯晃了一下。" * 40
)
PARA_QUOTE = "她站在塔下，抬头看着那盏灯。"


def test_rewrite_paragraph_only_touches_named_paragraph(tmp_path, monkeypatch):
    """只改第 2 段；首尾段原样保留，改完 quote 消失即算解决。"""
    root = make_book(tmp_path, PARA_TEXT)
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {
            "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 12,
            "model": "test-model", "usage": {"total_tokens": 8},
        }

    monkeypatch.setattr(review, "chat", fake_chat)
    res = review.rewrite_paragraph(
        root, 1, 2,
        finding={"severity": "mid", "message": "这句不像她", "quote": PARA_QUOTE, "hint": "写动作"},
    )

    assert res["resolved"] is True
    assert PARA_QUOTE not in res["text"]
    assert res["text"].count("塔顶的红灯亮起来") == 40
    assert res["text"].count("风从海面吹过来") == 40
    assert res["paragraph"] == 2
    assert "第 2 段" in seen["prompt"] and "这句不像她" in seen["prompt"]
    # 相邻段只给接缝处，不把整章塞进提示词。
    assert seen["prompt"].count("风从海面吹过来") < 40
    assert "上一段（只作衔接，不要重写）" in seen["prompt"]
    assert "下一段（只作衔接，不要重写）" in seen["prompt"]
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8").strip() == res["text"].strip()
    assert review.read_index_entry(root, 1)["approved"] is False

    drafts = list((root / "drafts").iterdir())
    assert len(drafts) == 1 and "-para2-" in drafts[0].name
    assert PARA_TEXT == drafts[0].read_text(encoding="utf-8")
    ledger = [
        json.loads(line) for line in (root / "ledger/review.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    row = next(r for r in ledger if r["kind"] == "paragraph-rewrite")
    assert row["paragraph"] == 2 and row["quote"] == PARA_QUOTE


def test_rewrite_paragraph_refuses_when_quote_remains(tmp_path, monkeypatch):
    root = make_book(tmp_path, PARA_TEXT)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": PARA_QUOTE * 30,  # 字数够，但问题原句还在
        "model": "test-model", "usage": {"total_tokens": 8},
    })
    with pytest.raises(review.ReviewError) as err:
        review.rewrite_paragraph(root, 1, 2, finding={"message": "不像她", "quote": PARA_QUOTE})
    assert "原句还在" in str(err.value)
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8") == PARA_TEXT
    assert list((root / "drafts").iterdir()) == []


def test_rewrite_paragraph_retries_when_quote_survives(tmp_path, monkeypatch):
    """模型常把被点名的句子换个说法留着；给一次明确重写的机会。"""
    root = make_book(tmp_path, PARA_TEXT)
    calls: list[str] = []
    good = "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 12

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return {
            "text": PARA_QUOTE * 30 if len(calls) == 1 else good,
            "model": "test-model", "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(review, "chat", fake_chat)
    res = review.rewrite_paragraph(root, 1, 2, finding={"message": "不像她", "quote": PARA_QUOTE})
    assert len(calls) == 2
    assert "上一版不合格" in calls[1] and PARA_QUOTE[:20] in calls[1]
    assert res["resolved"] is True


def test_paragraph_rewrite_resolves_finding_in_round(tmp_path, monkeypatch):
    """按段改完原句消失：这一轮里那条记成已解决，再复检不会再冒出来。"""
    root = make_book(tmp_path, PARA_TEXT)
    calls: list[int] = []

    def fake_chat(messages, **kwargs):
        calls.append(1)
        if "只输出改写后的第" in messages[-1]["content"]:
            return {
                "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 12,
                "model": "test-model", "usage": {"total_tokens": 5},
            }
        return ai_reply(messages, suggestions=[{
            "severity": "mid", "code": "motivation", "message": "这句不像她",
            "quote": PARA_QUOTE, "hint": "写动作",
        }])

    monkeypatch.setattr(review, "chat", fake_chat)
    first = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert first["standard"]["verdict"] == "minor"

    para = review.rewrite_paragraph(
        root, 1, 2, finding={"severity": "mid", "code": "motivation", "message": "这句不像她", "quote": PARA_QUOTE},
    )
    assert para["resolved"] is True
    assert len(calls) == 2

    again = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert len(calls) == 2  # 没有重新问模型
    assert again["carried"] is True
    assert not [f for f in again["findings"] if f.get("source") == "ai"]
    assert again["standard"]["verdict"] == "pass"
    assert again["resolvedCount"] == 1


def test_checklist_item_auto_resolves_when_quote_disappears(tmp_path, monkeypatch):
    """未过项的引用原句被改没了，本轮就自动算解决，不必作者再点一次。"""
    root = make_book(tmp_path, PARA_TEXT)

    def fake_chat(messages, **kwargs):
        if "只输出改写后的第" in messages[-1]["content"]:
            return {
                "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 12,
                "model": "test-model", "usage": {"total_tokens": 5},
            }
        return ai_reply(messages, fails={"internal": {
            "quote": PARA_QUOTE, "note": "前后对不上", "hint": "改成她看见的",
        }})

    monkeypatch.setattr(review, "chat", fake_chat)
    first = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert first["standard"]["verdict"] == "fail"
    assert {c["id"]: c["state"] for c in first["checklist"]}["internal"] == "fail"

    # 故意传错 code/message，模拟作者从旧面板点「改这一段」：quote 没了也要自动摘掉。
    review.rewrite_paragraph(
        root, 1, 2,
        finding={"severity": "high", "code": "voice", "message": "别的说法", "quote": PARA_QUOTE},
    )
    again = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert again["carried"] is True
    assert not [f for f in again["findings"] if f.get("source") == "ai"]
    assert again["standard"]["verdict"] == "pass"
    assert {c["id"]: c["state"] for c in again["checklist"]}["internal"] == "resolved"
    assert again["resolvedCount"] == 1


def test_rewrite_paragraph_rejects_misplaced_quote(tmp_path):
    root = make_book(tmp_path, PARA_TEXT)
    with pytest.raises(review.ReviewError) as err:
        # quote 在第 2 段，却要求改第 1 段
        review.rewrite_paragraph(root, 1, 1, finding={"quote": PARA_QUOTE})
    assert "不在第 1 段" in str(err.value)


def test_rewrite_paragraph_stream_route(tmp_path, monkeypatch):
    root = make_book(tmp_path, PARA_TEXT)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "她把伞收起来，沿着塔基走了一圈。" * 12,
        "model": "test-model", "usage": {"total_tokens": 6},
    })
    events: list[dict] = []
    with client.stream(
        "POST", "/api/projects/chapters/1/rewrite-paragraph/stream",
        params={"dir": str(root)},
        json={"paragraph": 2, "finding": {"message": "不像她", "quote": PARA_QUOTE, "severity": "mid"}},
    ) as res:
        assert res.status_code == 200
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

    assert events[-1]["type"] == "done"
    done = events[-1]["result"]
    assert done["resolved"] is True and done["paragraph"] == 2


def test_ai_check_merges_findings(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda messages, **k: ai_reply(
        messages,
        suggestions=[{
            "severity": "mid", "code": "repetition", "message": "季恒这句说了两遍",
            "quote": "他把最后一颗螺丝拧紧", "hint": "删一处",
        }],
    ))
    r = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert any(f["code"] == "repetition" for f in r.json()["findings"])


def test_ai_check_tolerates_wrapped_and_fenced_json(tmp_path, monkeypatch):
    """模型爱加解释、包成对象、留尾逗号；这些都不该让复检 502。"""
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda messages, **k: ai_reply(
        messages,
        suggestions=[{
            "severity": "mid", "code": "repetition", "message": "同一句说了两遍",
            "quote": "他把最后一颗螺丝拧紧", "hint": "删一处",
        }],
        wrap=True,
    ))
    r = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert any(f["message"] == "同一句说了两遍" for f in r.json()["findings"])


def test_ai_check_repairs_broken_output_once(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        if len(calls) == 1:
            return {
                "text": "我觉着这一章还行，没什么大问题。",
                "model": "test-model", "usage": {"total_tokens": 7},
            }
        return ai_reply(messages, fails={"internal": {
            "quote": "他把最后一颗螺丝拧紧", "note": "和第1章的时间对不上", "hint": "统一成夜里",
        }})

    monkeypatch.setattr(review, "chat", fake_chat)
    r = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    assert len(calls) == 2
    assert "【清单】" in calls[1]
    assert any("时间对不上" in f["message"] for f in r.json()["findings"])

    usage = (root / "metrics/usage.jsonl").read_text(encoding="utf-8").strip().splitlines()
    row = json.loads(usage[-1])
    assert row["kind"] == "ai-check" and row["tokens"] == 12


def test_ai_check_standard_requires_evidence(tmp_path, monkeypatch):
    """逐项判定：说不过却指不出正文原句的项不算；清单外的建议也不影响结论。"""
    root = make_book(tmp_path)
    (root / "ledger/outline.jsonl").write_text(json.dumps({
        "chapter": 1, "mustInclude": ["必须写灯灭"],
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    def fake_chat(messages, **kwargs):
        return ai_reply(
            messages,
            fails={
                # 细纲要求出现但没写：没有 quote 也算有效反证。
                "outline-include-0": {"note": "全章没写灯灭", "hint": "补一拍"},
                # 说章内矛盾却指不出原句：按拿不准处理，不计入。
                "internal": {"note": "前面天黑后面又天亮"},
                # 视角越界，有原句：计入。
                "pov": {"quote": "他把最后一颗螺丝拧紧", "note": "写了别人内心", "hint": "改成他看见的"},
            },
            suggestions=[
                {"severity": "high", "code": "voice", "message": "这句感觉不太对", "hint": "改"},
            ],
        )

    monkeypatch.setattr(review, "chat", fake_chat)
    body = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    messages = [f["message"] for f in body["findings"] if f.get("source") == "ai"]
    assert any(m.startswith("细纲要求出现但没写：必须写灯灭") for m in messages)
    assert "视角越界：写了别人内心" in messages
    assert not any("前面天黑" in m for m in messages)
    assert not any("感觉不太对" in m for m in messages)
    assert body["standard"]["verdict"] == "fail"
    assert body["standard"]["high"] == 2
    assert body["standard"]["items"] == 3
    assert body["standard"]["failed"] == 2
    assert body["standard"]["filtered"] == 2
    states = {c["id"]: c["state"] for c in body["checklist"]}
    assert states == {"outline-include-0": "fail", "internal": "skip", "pov": "fail"}

    # 清单全过、只剩无依据的“问题”时，结论通过，不再逼作者重写。
    monkeypatch.setattr(review, "chat", lambda messages, **k: ai_reply(
        messages,
        suggestions=[{
            "severity": "high", "code": "voice", "message": "这句感觉不太对",
            "quote": "他把最后一颗螺丝拧紧", "hint": "改",
        }],
    ))
    # 同一份输入默认沿用上次结论；这里要换一份假输出，必须显式 force。
    empty = client.post(
        "/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={"force": True},
    ).json()
    assert not [f for f in empty["findings"] if f.get("source") == "ai"]
    assert empty["standard"]["verdict"] == "pass"
    assert empty["standard"]["failed"] == 0
    assert empty["standard"]["filtered"] == 1


def test_ai_check_continues_round_instead_of_rescanning(tmp_path, monkeypatch):
    """同一章再点复检，返回的是这一轮修完剩下的条目，不重新出题。"""
    root = make_book(tmp_path)
    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return ai_reply(messages, suggestions=[{
            "severity": "mid", "code": "motivation", "message": "这句不像季恒",
            "quote": "他把最后一颗螺丝拧紧", "hint": "改短",
        }])

    monkeypatch.setattr(review, "chat", fake_chat)
    first = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    second = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert len(calls) == 1
    assert second["cached"] is True and second["carried"] is True
    assert second["round"] == first["round"]
    assert [f["message"] for f in second["findings"]] == [f["message"] for f in first["findings"]]

    # 作者明确要求「新一轮」时才重新问模型；新轮次替换旧轮次。
    fresh = client.post(
        "/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={"force": True},
    ).json()
    assert len(calls) == 2
    assert fresh["carried"] is False and fresh["round"] != first["round"]


def test_ai_check_resolve_trims_round_without_rescanning(tmp_path, monkeypatch):
    """手动确认一条已解决：从本轮摘掉，再点复检也不重新扫、不复活。"""
    root = make_book(tmp_path)
    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return ai_reply(
            messages,
            fails={"internal": {
                "quote": "他把最后一颗螺丝拧紧", "note": "时间对不上", "hint": "改成夜里",
            }},
            suggestions=[{
                "severity": "mid", "code": "motivation", "message": "这句不像季恒",
                "quote": "塔顶的红灯亮起来", "hint": "改短",
            }],
        )

    monkeypatch.setattr(review, "chat", fake_chat)
    first = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert first["standard"]["verdict"] == "fail"
    hard = next(f for f in first["findings"] if f.get("severity") == "high" and f.get("source") == "ai")
    assert hard["message"] == "本章前后矛盾：时间对不上"

    r = client.post(
        "/api/projects/chapters/1/ai-check/resolve", params={"dir": str(root)},
        json={"code": "continuity", "message": hard["message"]},
    )
    assert r.status_code == 200, r.text
    trimmed = r.json()
    ai = [f for f in trimmed["findings"] if f.get("source") == "ai"]
    assert [f["message"] for f in ai] == ["这句不像季恒"]
    assert trimmed["standard"]["verdict"] == "minor"
    assert trimmed["standard"]["failed"] == 0
    assert trimmed["standard"]["resolved"] == 1
    assert len(calls) == 1

    again = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert len(calls) == 1
    assert [f["message"] for f in again["findings"] if f.get("source") == "ai"] == ["这句不像季恒"]

    # 不在本轮里的条目不能假装解决成功。
    bad = client.post(
        "/api/projects/chapters/1/ai-check/resolve", params={"dir": str(root)},
        json={"code": "voice", "message": "这条根本不存在"},
    )
    assert bad.status_code == 400
    assert "不在本轮复检里" in bad.json()["detail"]


def test_ai_check_round_ends_on_full_rewrite(tmp_path, monkeypatch):
    """整章改写换了稿，旧轮次作废；再点复检才重新出题。"""
    root = make_book(tmp_path)
    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        if "只输出改写后的正文" in messages[-1]["content"] or "按编辑意见修改" in messages[0]["content"]:
            return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 5}}
        return ai_reply(messages, suggestions=[{
            "severity": "mid", "code": "motivation", "message": "这句不像季恒",
            "quote": "他把最后一颗螺丝拧紧", "hint": "改短",
        }])

    monkeypatch.setattr(review, "chat", fake_chat)
    client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    before = len(calls)
    review.rewrite_chapter(root, 1, skills=["deai"])
    after_rewrite = len(calls)

    res = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    assert len(calls) == after_rewrite + 1
    assert res["carried"] is False
    assert len(calls) > before


def test_ai_check_unparseable_returns_502(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "这一章很流畅，没有问题。", "model": "test-model", "usage": {"total_tokens": 5},
    })
    r = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={})
    assert r.status_code == 502
    assert "逐项判定" in r.json()["detail"]


def test_ai_check_carries_cross_chapter_context(tmp_path, monkeypatch):
    """复检要能看到前情、上一章结尾和本章细纲，跨章吃书才有判断依据。"""
    root = make_book(tmp_path)
    chapter2 = "他推开门，塔顶的灯已经灭了。"
    body2 = "chapters/002-第二天.md"
    (root / body2).write_text(chapter2, encoding="utf-8")
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    index.append({
        "number": 2, "title": "第二天", "file": body2, "chars": len(chapter2),
        "summary": "第二天灯灭了。", "characters": ["季恒"], "approved": False,
        "chapterVerdict": "pass", "verdict": "良", "fixReasons": [], "dialogueRatio": 0.1,
    })
    (root / "chapters/index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (root / "ledger/memory.jsonl").write_text("\n".join([
        json.dumps({
            "chapter": 1, "title": "第一段广播", "summary": "季恒修好塔顶红灯。",
            "events": ["塔顶红灯亮起来"], "characters": ["季恒"], "state": "结束时塔顶亮灯",
        }, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    (root / "ledger/outline.jsonl").write_text(json.dumps({
        "chapter": 2, "title": "第二天", "beats": ["灯先灭再亮"],
        "mustInclude": ["必须写灯灭"], "mustAvoid": ["不要写新角色"],
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    seen: list[str] = []

    def fake_chat(messages, **kwargs):
        seen.append(messages[-1]["content"])
        return ai_reply(messages)

    monkeypatch.setattr(review, "chat", fake_chat)
    result = review.ai_check_chapter(root, 2)
    prompt = seen[0]
    assert "季恒修好塔顶红灯" in prompt
    assert "塔顶红灯亮起来" in prompt
    assert "他把最后一颗螺丝拧紧" in prompt      # 上一章结尾原文
    assert "必须出现：必须写灯灭" in prompt
    assert "必须回避：不要写新角色" in prompt
    assert result["context"] == {"priorChapters": 1, "prevTail": True, "outline": True}
    # 固定清单：细纲两项 + 接缝 + 章内一致 + 视角。
    assert {c["id"] for c in result["checklist"]} >= {
        "outline-include-0", "outline-avoid-0", "seam", "internal", "pov",
    }
    assert result["standard"]["verdict"] == "pass"


def test_ai_check_stream_emits_reason_then_result(tmp_path, monkeypatch):
    root = make_book(tmp_path)

    def fake_chat(messages, **kwargs):
        on_reason = kwargs.get("on_reason")
        if on_reason:
            on_reason("先对照前情，再看本章接缝")
        reply = ai_reply(messages, suggestions=[{
            "severity": "mid", "code": "motivation", "message": "这句不像季恒",
            "quote": "他把最后一颗螺丝拧紧", "hint": "改短",
        }])
        reply["reason"] = "先对照前情，再看本章接缝"
        return reply

    monkeypatch.setattr(review, "chat", fake_chat)
    events: list[dict] = []
    with client.stream(
        "POST", "/api/projects/chapters/1/ai-check/stream",
        params={"dir": str(root)}, json={},
    ) as res:
        assert res.status_code == 200
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

    kinds = [e["type"] for e in events]
    assert "reason" in kinds and kinds[-1] == "done"
    assert "先对照前情" in "".join(e.get("text", "") for e in events if e["type"] == "reason")
    done = events[-1]["result"]
    assert done["thinking"].startswith("先对照前情")
    assert any(f["code"] == "motivation" for f in done["findings"])
    assert done["standard"]["verdict"] == "minor"


def test_ai_check_stream_falls_back_to_preface(tmp_path, monkeypatch):
    """模型不吐 reasoning_content 时，JSON 前面的审稿思路就是思考过程，且不把 JSON 倒给前端。"""
    root = make_book(tmp_path)
    preface = "我先对照上一章结尾，再看本章开场，时间线最可疑。\n\n"

    def fake_chat(messages, **kwargs):
        on_delta = kwargs.get("on_delta")
        body_json = ai_reply(messages, suggestions=[{
            "severity": "mid", "code": "repetition", "message": "时间对不上",
            "quote": "他把最后一颗螺丝拧紧", "hint": "改",
        }])["text"]
        for piece in (preface, body_json):
            if on_delta:
                on_delta(piece)
        return {
            "text": preface + body_json,
            "reason": "", "model": "test-model", "usage": {"total_tokens": 4},
        }

    monkeypatch.setattr(review, "chat", fake_chat)
    events: list[dict] = []
    with client.stream(
        "POST", "/api/projects/chapters/1/ai-check/stream",
        params={"dir": str(root)}, json={},
    ) as res:
        for line in res.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

    streamed = "".join(e.get("text", "") for e in events if e["type"] == "reason")
    assert "时间线最可疑" in streamed
    assert "severity" not in streamed
    assert events[-1]["result"]["thinking"].startswith("我先对照上一章结尾")


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


def test_abandon_foreshadow_clears_overdue_blocking(tmp_path):
    """到期没收的伏笔会挂在按批体检的跨章问题上；点放弃后不该再追。"""
    root = make_book(tmp_path)
    row = client.post("/api/projects/foreshadow", params={"dir": str(root)}, json={
        "name": "后窗插销锈死", "kind": "detail", "plantedChapter": 1, "dueChapter": 2,
    }).json()["row"]

    batch = client.post("/api/projects/check-batch", params={"dir": str(root)},
                        json={"from": 1, "to": 2}).json()
    item = next(f for f in batch["blocking"] if f["code"] == "foreshadow-overdue")
    assert item["items"][0]["id"] == row["id"]
    assert item["items"][0]["dueChapter"] == 2
    assert item["items"][0]["overdueBy"] == 0

    r = client.post("/api/projects/foreshadow/abandon", params={"dir": str(root)},
                    json={"id": row["id"], "note": "这版不写这条线"})
    assert r.status_code == 200, r.text
    rows = client.get("/api/projects/ledger/foreshadow",
                      params={"dir": str(root), "folded": True}).json()["rows"]
    saved = next(f for f in rows if f["id"] == row["id"])
    assert saved["status"] == "abandoned"

    again = client.post("/api/projects/check-batch", params={"dir": str(root)},
                        json={"from": 1, "to": 2}).json()
    assert not any(f["code"] == "foreshadow-overdue" for f in again["blocking"])

    dup = client.post("/api/projects/foreshadow/abandon", params={"dir": str(root)},
                      json={"id": row["id"]})
    assert dup.status_code == 400


def test_generate_foreshadows_skips_renamed_duplicates(tmp_path, monkeypatch):
    """AI 补伏笔爱给旧线加个后缀再写一遍；同名/包含关系的不要重复入账。"""
    from app.domain import foreshadow_gen

    root = make_book(tmp_path)
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["worldText"] = "末日第七年，庇护所。"
    project["outlineText"] = "### 第1卷 名单（第1-30章）\n周砚管点名册。"
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (root / "ledger/foreshadow.jsonl").write_text(json.dumps({
        "id": "fs-old", "name": "我儿子名字还在吗", "kind": "detail",
        "plantedChapter": 5, "dueChapter": 11, "status": "open",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = "\n".join([
        "名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃",
        "我儿子名字还在吗问了三次|细节|人物·赵婶|5|拍2 赵婶探头|11|周砚|第三次问时名字已被划|她又来问|只问一次",
        "后窗插销锈死|细节|地点·登记室|2|拍1 擦窗推不动|4|赵婶|唯一退路失效|再擦一次|窗被钉死",
    ])

    def fake_chat(messages, **kwargs):
        return {"text": lines, "model": "m", "usage": {}}

    monkeypatch.setattr(foreshadow_gen, "chat", fake_chat)
    res = foreshadow_gen.generate_foreshadows(root)

    assert res["count"] == 1
    names = [r["name"] for r in foreshadow_gen.fold_foreshadow(
        foreshadow_gen.read_jsonl(root / "ledger/foreshadow.jsonl"))]
    assert names.count("我儿子名字还在吗") == 1
    assert "我儿子名字还在吗问了三次" not in names
    assert "后窗插销锈死" in names


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


def test_rewrite_prompt_carries_findings_from_ui(tmp_path, monkeypatch):
    """界面上体检/复检出的问题（含 AI 复检）要进改写提示词，按 message 去重、丢掉低优先级。"""
    root = make_book(tmp_path, SHORT)  # 短稿会命中确定性体检 words-below
    seen: dict[str, object] = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 320, "model": "test-model", "usage": {"total_tokens": 10}}

    monkeypatch.setattr(review, "chat", fake)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={
        "findings": [
            {"severity": "mid", "code": "voice", "message": "季恒这句不像他", "hint": "改短", "source": "ai"},
            {"severity": "mid", "code": "dup", "message": "季恒这句不像他", "hint": "重复条目", "source": "ai"},
            {"severity": "low", "code": "noise", "message": "低优先级不该进提示词", "source": "ai"},
        ],
    })
    assert r.status_code == 200, r.text
    user = next(m["content"] for m in seen["messages"] if m["role"] == "user")  # type: ignore[index]

    assert "必须改掉的问题" in user
    assert "季恒这句不像他" in user
    assert "改短" in user
    assert "[mid·复检]" in user
    assert user.count("季恒这句不像他") == 1  # 去重
    assert "低优先级不该进提示词" not in user
    assert "低于每章硬下限" in user  # 后端重跑的确定性体检也在
