"""审阅写回路：存档 / 退回 / 废章恢复 / 正文保存 / 体检 / 改写。

全部在 tmp 书目录里跑，不碰作者的两本真书。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain import metrics, review
from app.main import app
from app.store.jsonl import fold_foreshadow

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


def test_check_results_persist_and_recheck_changed_text(tmp_path):
    """体检结果落 ledger/checks.jsonl；正文改过就按当前稿重跑，改掉的问题自动消失。"""
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

    # 改成过短的稿：刷新后直接重跑体检，旧结论不再冒充当前结果。
    (root / "chapters/001-第一段广播.md").write_text(SHORT, encoding="utf-8")
    rows = client.get("/api/projects/checks", params={"dir": str(root)}).json()["rows"]
    assert rows[0]["stale"] is False
    assert rows[0]["result"]["pass"] is False

    # 改回合格稿：硬伤消失，缓存跟着翻回通过。
    (root / "chapters/001-第一段广播.md").write_text(LONG, encoding="utf-8")
    rows = client.get("/api/projects/checks", params={"dir": str(root)}).json()["rows"]
    assert rows[0]["stale"] is False
    assert rows[0]["result"]["pass"] is True


def test_check_batch_shape(tmp_path):
    root = make_book(tmp_path)
    r = client.post("/api/projects/check-batch", params={"dir": str(root)}, json={"from": 1, "to": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == 1 and body["to"] == 1
    assert body["chapters"][0]["number"] == 1
    assert isinstance(body["blocking"], list)


def test_dismiss_deterministic_finding(tmp_path):
    """确定性体检的误报可以按命中句忽略；重跑后只剩没被忽略的那条。"""
    root = make_book(tmp_path)
    text = LONG + "\n\n不是他忘了，而是他不敢说。不是门锁坏了，而是有人从里面焊死了。"
    (root / "chapters/001-第一段广播.md").write_text(text, encoding="utf-8")

    single = client.get("/api/projects/chapters/1/check", params={"dir": str(root)}).json()
    cat = next(c for c in single["aiTells"]["categories"] if c["id"] == "not-x-but-y")
    assert cat["count"] == 2 and len(cat["samples"]) == 2
    first = cat["samples"][0]

    r = client.post(
        "/api/projects/chapters/1/check/dismiss",
        params={"dir": str(root)},
        json={
            "code": "ai-tell-not-x-but-y",
            "quote": first["text"],
            "line": first["line"],
            "offset": first["offset"],
        },
    )
    assert r.status_code == 200, r.text
    fresh = r.json()["check"]
    cat = next(c for c in fresh["aiTells"]["categories"] if c["id"] == "not-x-but-y")
    assert cat["count"] == 1
    assert all(s["text"] != first["text"] for s in cat["samples"])
    assert any(f["code"] == "ai-tell-not-x-but-y" for f in fresh["findings"])

    # 忽略落盘：再体检一次也不会把误报带回来
    again = client.get("/api/projects/chapters/1/check", params={"dir": str(root)}).json()
    cat = next(c for c in again["aiTells"]["categories"] if c["id"] == "not-x-but-y")
    assert cat["count"] == 1


def test_settings_write_back_waits_for_whole_batch(tmp_path):
    """正文落盘只记章记忆；这一批全部存档后才把位置/物品并进设定。"""
    root = make_book(tmp_path)
    body2 = "chapters/002-第二天.md"
    (root / body2).write_text(LONG, encoding="utf-8")
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    index.append({
        "number": 2, "title": "第二天", "file": body2, "chars": len(LONG),
        "summary": "第二天他爬上塔顶。", "characters": ["季恒"], "approved": False,
        "chapterVerdict": "pass", "verdict": "良", "fixReasons": [], "dialogueRatio": 0.1,
    })
    (root / "chapters/index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    bible["items"] = [{"name": "扳手"}]
    (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    # 按批体检定下「这一批」：之后存档要等这两章都过。
    client.post("/api/projects/check-batch", params={"dir": str(root)}, json={"from": 1, "to": 2})
    (root / "ledger/memory.jsonl").write_text("\n".join([
        json.dumps({
            "kind": "chapter", "chapter": 1,
            "moves": [{"who": "季恒", "to": "塔下"}],
            "items": [{"name": "扳手", "holder": "老周"}],
        }, ensure_ascii=False),
        json.dumps({
            "kind": "chapter", "chapter": 2,
            "moves": [{"who": "季恒", "to": "塔顶"}],
            "items": [{"name": "扳手", "holder": "季恒", "state": "断了"}],
        }, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    first = client.post("/api/projects/chapters/1/archive", params={"dir": str(root)}, json={}).json()
    assert first["settingsApplied"] == {"moves": 0, "items": 0, "factions": 0, "places": 0, "characters": 0}
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    assert not bible["characters"][0].get("locationHistory")
    assert not bible["items"][0].get("holder")

    second = client.post("/api/projects/chapters/2/archive", params={"dir": str(root)}, json={}).json()
    assert second["settingsApplied"]["moves"] == 2
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    assert bible["characters"][0]["location"] == "塔顶"
    assert bible["characters"][0]["locationAt"] == 2
    assert bible["items"][0]["holder"] == "季恒"


def test_check_batch_merges_duplicate_overdue_lines(tmp_path):
    """同章埋、同章收的重复录入合成一行；标一次要能一起处理。"""
    root = make_book(tmp_path)
    rows = [
        {"id": "fs-a1", "name": "五点四十就到了", "kind": "detail",
         "plantedChapter": 1, "dueChapter": 1, "status": "open"},
        {"id": "fs-a2", "name": "五点四十就到了却从不进登记室", "kind": "detail",
         "plantedChapter": 1, "dueChapter": 1, "status": "open"},
        {"id": "fs-b1", "name": "后窗插销锈死", "kind": "detail",
         "plantedChapter": 1, "dueChapter": 1, "status": "open"},
    ]
    (root / "ledger/foreshadow.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    body = client.post(
        "/api/projects/check-batch", params={"dir": str(root)}, json={"from": 1, "to": 1},
    ).json()
    blocking = body["blocking"][0]
    assert len(blocking["items"]) == 2
    merged = next(it for it in blocking["items"] if it["duplicates"])
    assert merged["name"] == "五点四十就到了却从不进登记室"
    assert set(merged["ids"]) == {"fs-a1", "fs-a2"}
    assert merged["duplicates"] == 1
    assert "含 1 条重复" in blocking["message"]


def test_batch_auto_records_ai_confirmed_payoff(tmp_path):
    """AI 复检的收线项判过了：正文已写，按批体检直接记收，不再挂成到期。"""
    root = make_book(tmp_path)
    rows = [
        {"id": "fs-a1", "name": "我儿子名字还在吗", "kind": "detail",
         "plantedChapter": 1, "dueChapter": 1, "status": "open"},
        {"id": "fs-a2", "name": "我儿子名字还在吗问了三次", "kind": "detail",
         "plantedChapter": 1, "dueChapter": 1, "status": "open"},
    ]
    (root / "ledger/foreshadow.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8",
    )
    (root / "ledger/checks.jsonl").write_text(json.dumps({
        "kind": "ai-round", "chapter": 1, "round": "r-test",
        "version": review.AI_CHECK_VERSION, "textHash": "", "at": "",
        "result": {
            "number": 1, "findings": [], "groups": [],
            "checklist": [{
                "id": "outline-include-0",
                "label": "细纲必须出现：收第5章伏笔：我儿子名字还在吗",
                "state": "pass",
            }],
        },
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    body = client.post(
        "/api/projects/check-batch", params={"dir": str(root)}, json={"from": 1, "to": 1},
    ).json()
    assert body["blocking"] == []
    assert body["autoPaid"] == [{
        "name": "我儿子名字还在吗问了三次", "chapter": 1,
        "ids": ["fs-a1", "fs-a2"], "via": "ai-check",
    }]
    paid = [r for r in foreshadow_rows(root) if r.get("op") == "payoff"]
    assert {r["id"] for r in paid} == {"fs-a1", "fs-a2"}
    assert "AI 复检" in paid[0]["note"]


def seed_foreshadow(root: Path, **row) -> None:
    base = {"id": "fs-1", "name": "后窗插销锈死", "kind": "detail",
            "plantedChapter": 1, "dueChapter": 1, "status": "open"}
    (root / "ledger/foreshadow.jsonl").write_text(
        json.dumps({**base, **row}, ensure_ascii=False) + "\n", encoding="utf-8",
    )


def foreshadow_rows(root: Path) -> list[dict]:
    return [
        json.loads(line) for line in
        (root / "ledger/foreshadow.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_check_batch_verifies_payoff_and_records_it(tmp_path, monkeypatch):
    """按批体检核对正文：已经收了的自动记账，不再挂成「到期没收」。"""
    root = make_book(tmp_path)
    seed_foreshadow(root, plantBeat="他推后窗，插销锈死", revealChange="后窗一直没开过")
    calls = {"n": 0}

    def fake_chat(messages, **kwargs):
        calls["n"] += 1
        prompt = messages[-1]["content"]
        assert "后窗插销锈死" in prompt
        assert "=== 第1章 ===" in prompt
        assert "插销锈死" in prompt  # 埋点也给了，模型才知道该找什么
        return {"text": json.dumps({"items": [{
            "id": "fs-1", "collected": True, "chapter": 1,
            "evidence": "他把最后一颗螺丝拧紧",
        }]}, ensure_ascii=False), "model": "fake", "usage": {}}

    monkeypatch.setattr(review, "chat", fake_chat)
    body = client.post(
        "/api/projects/check-batch", params={"dir": str(root)},
        json={"from": 1, "to": 1, "verify": True},
    ).json()
    assert body["blocking"] == []
    assert body["autoPaid"] == [
        {"name": "后窗插销锈死", "chapter": 1, "ids": ["fs-1"], "via": "text"},
    ]
    last = foreshadow_rows(root)[-1]
    assert last["op"] == "payoff" and last["payoffChapter"] == 1
    assert "按批体检核对" in last["note"]

    # 同样的清单 + 同样的正文：命中缓存，不再调模型；提醒也不会回来。
    again = client.post(
        "/api/projects/check-batch", params={"dir": str(root)},
        json={"from": 1, "to": 1, "verify": True},
    ).json()
    assert calls["n"] == 1
    assert again["blocking"] == []


def test_check_batch_ignores_verdict_without_quote_in_text(tmp_path, monkeypatch):
    """模型说收了、却引不出正文原句：不记账，照旧挂提醒。"""
    root = make_book(tmp_path)
    seed_foreshadow(root)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": json.dumps({"items": [{
            "id": "fs-1", "collected": True, "chapter": 1,
            "evidence": "这句正文里根本没有",
        }]}, ensure_ascii=False),
        "model": "fake", "usage": {},
    })
    body = client.post(
        "/api/projects/check-batch", params={"dir": str(root)},
        json={"from": 1, "to": 1, "verify": True},
    ).json()
    assert body["autoPaid"] == []
    assert body["blocking"][0]["items"][0]["id"] == "fs-1"
    assert len(foreshadow_rows(root)) == 1  # 只有原始那一行，没有追加记收


def test_check_batch_keeps_working_when_verify_model_fails(tmp_path, monkeypatch):
    """核对调用失败不能把整批体检拖死：日志留痕，提醒照常显示。"""
    root = make_book(tmp_path)
    seed_foreshadow(root)

    def boom(*a, **k):
        raise review.LLMError("网关不通")

    monkeypatch.setattr(review, "chat", boom)
    body = client.post(
        "/api/projects/check-batch", params={"dir": str(root)},
        json={"from": 1, "to": 1, "verify": True},
    ).json()
    assert body["chapters"][0]["number"] == 1
    assert body["blocking"][0]["items"][0]["id"] == "fs-1"


def test_reopen_foreshadow_clears_payoff(tmp_path):
    """自动记收判错了能改回来：账本只追加 reopen，收线章清空。"""
    root = make_book(tmp_path)
    seed_foreshadow(root)
    client.post("/api/projects/foreshadow/payoff", params={"dir": str(root)},
                json={"id": "fs-1", "chapter": 1})
    r = client.post("/api/projects/foreshadow/reopen", params={"dir": str(root)},
                    json={"id": "fs-1"})
    assert r.status_code == 200, r.text
    [folded] = [f for f in fold_foreshadow(foreshadow_rows(root)) if f["id"] == "fs-1"]
    assert folded["status"] == "open"
    assert not folded.get("payoffChapter")

    again = client.post("/api/projects/foreshadow/reopen", params={"dir": str(root)},
                        json={"id": "fs-1"})
    assert again.status_code == 400


def test_ai_check_lists_foreshadow_obligations(tmp_path, monkeypatch):
    """AI 复检清单里要有本章该埋/该收的伏笔，不只是细纲。"""
    root = make_book(tmp_path)
    (root / "ledger/foreshadow.jsonl").write_text("\n".join([
        json.dumps({"id": "fs-due", "name": "后窗插销锈死", "kind": "detail",
                    "plantedChapter": 1, "dueChapter": 1, "status": "open",
                    "revealChange": "后窗一直没开过"}, ensure_ascii=False),
        json.dumps({"id": "fs-plant", "name": "塔顶第三颗螺丝", "kind": "detail",
                    "plantedChapter": 1, "dueChapter": 5, "status": "open",
                    "plantBeat": "他多拧了半圈"}, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    seen: list[str] = []

    def fake_chat(messages, **kwargs):
        seen.append(messages[-1]["content"])
        return ai_reply(messages, fails={
            "foreshadow-due-0": {"note": "全章没提后窗", "hint": "补一拍"},
        })

    monkeypatch.setattr(review, "chat", fake_chat)
    body = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    prompt = seen[0]
    # 提示词里每一项给的是「要求」原文，不是 label。
    assert "本章把伏笔「后窗插销锈死」收回来了" in prompt
    assert "本章埋下伏笔「塔顶第三颗螺丝」" in prompt
    assert {i["id"] for i in prompt_items(prompt)} >= {"foreshadow-due-0", "foreshadow-plant-0"}
    states = {c["id"]: c["state"] for c in body["checklist"]}
    assert states["foreshadow-due-0"] == "fail"
    assert states["foreshadow-plant-0"] == "pass"

    finding = next(f for f in body["findings"] if f.get("checkId") == "foreshadow-due-0")
    assert finding["severity"] == "mid"  # 伏笔是提醒，不是硬伤：不逼整章重写
    assert finding["message"].startswith("伏笔到期没收：后窗插销锈死")
    assert body["standard"]["verdict"] == "minor"  # 只有 mid 提醒 → 不算硬伤，不逼重写


def test_ai_check_lists_setting_and_rule_items(tmp_path, monkeypatch):
    """固定设定也要查：本章出现的物品/地点/势力对设定，世界硬规则逐条判。"""
    root = make_book(tmp_path)
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    bible["items"] = [{"name": "扳手", "origin": "从值班室工具箱顺来的"},
                      {"name": "信号灯", "origin": "塔顶最后一件能亮的东西"}]
    bible["rules"] = [{"name": "册上有名才算人", "judge": "配给按晨点名单发"}]
    (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    (root / "chapters/001-第一段广播.md").write_text(
        LONG + "\n\n他把扳手塞进腰后。", encoding="utf-8",
    )
    seen: list[str] = []

    def fake_chat(messages, **kwargs):
        seen.append(messages[-1]["content"])
        return ai_reply(messages)

    monkeypatch.setattr(review, "chat", fake_chat)
    body = client.post("/api/projects/chapters/1/ai-check", params={"dir": str(root)}, json={}).json()
    prompt = seen[0]
    # 正文里出现过的物品才进清单；没出现的信号灯不问。
    assert "本章出现的物品与设定一致「扳手」" in prompt
    assert "信号灯" not in prompt.split("【判定清单")[1]
    assert "本章没有违反下列世界硬规则" in prompt
    assert "册上有名才算人" in prompt
    ids = {c["id"] for c in body["checklist"]}
    assert {"setting-物品-0", "world-rules"} <= ids


def test_rewrite_uses_model_and_keeps_old_draft(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "改过的正文。" * 400, "model": "test-model",
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


def test_rewrite_expands_when_below_hard_floor(tmp_path, monkeypatch):
    """改写后低于硬下限：先把字数要求写进提示词，再补写一次，不直接把短稿落盘。"""
    root = make_book(tmp_path)  # 目标 2000 字，长篇硬下限 1800
    calls: list[str] = []

    def fake(messages, **kwargs):
        calls.append(messages[-1]["content"])
        text = "改过的正文。" * 320 if len(calls) == 1 else "改过的正文。" * 400
        return {"text": text, "model": "test-model", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(review, "chat", fake)
    res = review.rewrite_chapter(root, 1)

    assert len(calls) == 2
    assert "硬下限 1800 字" in calls[0]           # 提示词里就写明
    assert "低于本章硬下限 1800 字" in calls[1]   # 补写时说明差多少
    assert res["chars"] >= 1800


def test_rewrite_refuses_below_hard_floor(tmp_path, monkeypatch):
    """补写还是不够硬下限：拒绝落盘，旧稿与索引都不动。"""
    root = make_book(tmp_path)
    before = (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8")
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "改过的正文。" * 320, "model": "test-model", "usage": {"total_tokens": 5},
    })
    with pytest.raises(review.ReviewError) as err:
        review.rewrite_chapter(root, 1)
    assert "硬下限 1800 字" in str(err.value)
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8") == before
    assert list((root / "drafts").iterdir()) == []


def test_rewrite_paragraph_wont_shrink_chapter_below_floor(tmp_path, monkeypatch):
    """本章已经不到硬下限：改一段不许再把它改薄，提示词直接给这一段的字数下限。"""
    body = "他把最后一颗螺丝拧紧，塔顶的红灯亮起来。" * 60 + "\n\n" + "她站在塔下。" * 24
    root = make_book(tmp_path, body)
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {"text": "她站了一会儿。" * 3, "model": "test-model", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(review, "chat", fake_chat)

    with pytest.raises(review.ReviewError) as err:
        review.rewrite_paragraph(root, 1, 2)
    assert "改写后这一段过短" in str(err.value)
    assert "改写后这一段不能少于 120 字" in seen["prompt"]
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8") == body


def test_check_chars_rule_uses_book_hard_floor(tmp_path):
    """字数条要看硬下限：1600 字在「目标 75%」之上，但不到 1800，得报红。"""
    root = make_book(tmp_path, "他把最后一颗螺丝拧紧。" * 160)  # 1600 字
    result = review.check_chapter(root, 1)
    rule = next(x for x in result["rules"] if x["id"] == "chars")
    assert rule["state"] == "bad"
    assert "硬下限 1800 字" in rule["message"]
    assert any(f["code"] == "words-below" and f["severity"] == "high" for f in result["findings"])


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


def seed_extra_chapter(root: Path, number: int, title: str, text: str) -> None:
    """往 make_book 的测试书里再加一章（写正文 + 补 index）。"""
    rel = f"chapters/{number:03d}-{title}.md"
    (root / rel).write_text(text, encoding="utf-8")
    index = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    index.append({
        "number": number, "title": title, "file": rel, "chars": len(text),
        "summary": "", "characters": [], "approved": False,
    })
    (root / "chapters/index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def test_rewrite_paragraph_reads_adjacent_chapters(tmp_path, monkeypatch):
    """改段时要接得上上下章；没有上一章/下一章就整块不给。"""
    root = make_book(tmp_path, "上一章最后一句停在门口。")
    seed_extra_chapter(root, 2, "第二段广播", "她把门推开。\n墙后没有人。\n风从窗缝里进来。")
    seed_extra_chapter(root, 3, "第三段广播", "下一章开头就是那盏没亮的灯。")
    prompts: list[str] = []

    def fake_chat(messages, **kwargs):
        prompts.append(messages[-1]["content"])
        return {
            "text": "她把门推开，门后空着，风从窗缝里挤进来，吹得灯芯歪了一下。",
            "model": "test-model", "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(review, "chat", fake_chat)

    review.rewrite_paragraph(root, 2, 2, finding={"message": "太平", "quote": "墙后没有人"})
    assert "【上一章结尾（只作衔接，不要照抄）】" in prompts[0]
    assert "上一章最后一句停在门口。" in prompts[0]
    assert "【下一章开头（只作衔接，不要照抄）】" in prompts[0]
    assert "下一章开头就是那盏没亮的灯。" in prompts[0]

    # 第 1 章没有上一章：整块不给，不塞占位符让模型去编。
    review.rewrite_paragraph(root, 1, 1)
    assert "上一章结尾" not in prompts[1]
    # 第 1 章的下一章现在有正文了，照样给。
    assert "第二段广播" not in prompts[1]  # 提示词里只有正文，不塞标题
    assert "她把门推开。" in prompts[1]


def test_rewrite_chapter_prompt_reads_adjacent_chapters(tmp_path):
    """整章改写同样看上下章；没有的章整块不给，不塞「（没有上一章）」。"""
    root = make_book(tmp_path, LONG)
    seed_extra_chapter(root, 2, "第二段广播", "下一章开头就是那盏没亮的灯。")
    seed_extra_chapter(root, 3, "第三段广播", LONG)

    def prompt_for(n: int) -> str:
        entry = review.read_index_entry(root, n)
        msgs = review._build_rewrite_messages(
            root, n, entry, review.read_chapter(root, n) or "", "", "",
            review.check_chapter(root, n), ["deai"],
        )
        return msgs[-1]["content"]

    first = prompt_for(1)
    assert "【上一章结尾（只作衔接，不要复述）】" not in first
    assert "（没有上一章）" not in first
    assert "【下一章开头（只作衔接，不要复述）】" in first
    assert "下一章开头就是那盏没亮的灯。" in first

    second = prompt_for(2)
    assert "【上一章结尾（只作衔接，不要复述）】" in second
    assert "他把最后一颗螺丝拧紧" in second          # 上一章结尾原文
    assert "【下一章开头（只作衔接，不要复述）】" in second


def test_rewrite_paragraph_only_touches_named_paragraph(tmp_path, monkeypatch):
    """只改第 2 段；首尾段原样保留，改完 quote 消失即算解决。"""
    root = make_book(tmp_path, PARA_TEXT)
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {
            "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 30,
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
        "text": PARA_QUOTE * 45,  # 字数够，但问题原句还在
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
    good = "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 30

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        return {
            "text": PARA_QUOTE * 45 if len(calls) == 1 else good,
            "model": "test-model", "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(review, "chat", fake_chat)
    res = review.rewrite_paragraph(root, 1, 2, finding={"message": "不像她", "quote": PARA_QUOTE})
    assert len(calls) == 2
    assert "上一版不合格" in calls[1] and PARA_QUOTE[:20] in calls[1]
    assert res["resolved"] is True


def test_rewrite_paragraph_clears_tell_pattern_not_just_quote(tmp_path, monkeypatch):
    """AI 痕迹硬规则要按「这一类句式清零」验收，不能只把原句换个说法。"""
    filler = "他把册子摊在桌上，指尖压住页角。"
    root = make_book(tmp_path, "不是抽屉，是册页。" + filler * 18)
    calls: list[str] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages[-1]["content"])
        if len(calls) == 1:
            # 原句没了，但同类对举句式还在：不算改好。
            text = "这不是柜子，是册页。" + filler * 18
        else:
            text = "他把册子摊在桌上，翻到那一页。" * 25
        return {"text": text, "model": "test-model", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(review, "chat", fake_chat)
    res = review.rewrite_paragraph(
        root, 1, 1,
        finding={
            "severity": "high", "code": "ai-tell-not-x-but-y",
            "message": "不是A，而是B 对举句：不是抽屉，是册页。",
            "quote": "不是抽屉，是册页。", "paragraph": 1,
            "hint": "删掉对举，直接写实际发生的事",
        },
    )
    assert len(calls) == 2
    assert "还没改干净" in calls[1] or "上一版不合格" in calls[1]
    assert res["resolved"] is True
    assert "不是" not in res["text"]


def test_rewrite_paragraph_refuses_when_tell_pattern_survives(tmp_path, monkeypatch):
    """两次都只换说法、同类句式还在：旧稿不动，让作者知道没改好。"""
    filler = "他把册子摊在桌上，指尖压住页角。"
    text = "不是抽屉，是册页。" + filler * 18
    root = make_book(tmp_path, text)
    monkeypatch.setattr(review, "chat", lambda *a, **k: {
        "text": "这不是柜子，是册页。" + filler * 18,
        "model": "test-model", "usage": {"total_tokens": 5},
    })
    with pytest.raises(review.ReviewError) as err:
        review.rewrite_paragraph(
            root, 1, 1,
            finding={
                "severity": "high", "code": "ai-tell-not-x-but-y",
                "message": "不是A，而是B 对举句", "quote": "不是抽屉，是册页。",
                "paragraph": 1,
            },
        )
    assert "还没改干净" in str(err.value)
    assert (root / "chapters/001-第一段广播.md").read_text(encoding="utf-8") == text


ONE_LINE_TEXT = (
    "他把最后一颗螺丝拧紧。\n"
    "她没有在认人，是在把人往外捞。\n"
    "风从海面吹过来。\n"
    "灯晃了一下。"
)


def test_rewrite_paragraph_splits_single_newline_chapter(tmp_path, monkeypatch):
    """整章只按一次回车分段时，第 k 段是一行，不是整章。"""
    root = make_book(tmp_path, ONE_LINE_TEXT)
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {
            "text": "她没有认人，只是把这个人从记忆深处往外头捞了一把。",
            "model": "test-model", "usage": {"total_tokens": 5},
        }

    monkeypatch.setattr(review, "chat", fake_chat)
    assert review._paragraph_index(ONE_LINE_TEXT, "没有在认人") == 2
    res = review.rewrite_paragraph(
        root, 1, 2,
        finding={"severity": "mid", "message": "对举句", "quote": "她没有在认人"},
    )

    # 只换第 2 行：首尾两行、换行数原样保留。
    assert res["paragraph"] == 2
    assert res["text"] == (
        "他把最后一颗螺丝拧紧。\n"
        "她没有认人，只是把这个人从记忆深处往外头捞了一把。\n"
        "风从海面吹过来。\n"
        "灯晃了一下。"
    )
    assert "第 2 段，共 4 段" in seen["prompt"]
    target = seen["prompt"].split("【要改的段落")[1].split("【下一段")[0]
    assert "他把最后一颗螺丝" not in target and "灯晃了一下" not in target


def test_long_block_stays_one_paragraph():
    """一块里有超过单段上限的行：不逐行拆，仍按空行分段。"""
    long_line = "他把册子摊在桌上，指尖压住页角。" * 20
    text = long_line + "\n" + "她又翻过一页。"
    assert len(review._paragraph_chunks(text)) == 1
    assert metrics.paragraph_texts(text) == [text]


def test_load_checks_recomputes_when_metrics_version_changed(tmp_path):
    """正文没改、但分段口径改过：旧体检的段号不可信，必须按新口径重算。"""
    root = make_book(tmp_path, "他把门推开。\n墙后没有人。")
    (root / "ledger/checks.jsonl").write_text(json.dumps({
        "kind": "check", "chapter": 1, "textHash": "",
        "at": "2026-01-01T00:00:00.000Z",
        "result": {"number": 1, "pass": True, "findings": []},
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = review.load_checks(root)
    assert len(rows) == 1
    assert rows[0]["stale"] is False
    assert rows[0]["result"]["metricsVersion"] == metrics.METRICS_VERSION


def test_paragraph_rewrite_resolves_finding_in_round(tmp_path, monkeypatch):
    """按段改完原句消失：这一轮里那条记成已解决，再复检不会再冒出来。"""
    root = make_book(tmp_path, PARA_TEXT)
    calls: list[int] = []

    def fake_chat(messages, **kwargs):
        calls.append(1)
        if "只输出改写后的第" in messages[-1]["content"]:
            return {
                "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 30,
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
                "text": "她把伞收起来，沿着塔基走了一圈，脚步很慢。" * 30,
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
        "text": "她把伞收起来，沿着塔基走了一圈。" * 35,
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


def test_add_foreshadow_rejects_duplicate(tmp_path):
    root = make_book(tmp_path)
    first = client.post("/api/projects/foreshadow", params={"dir": str(root)}, json={
        "name": "后窗插销锈死", "plantedChapter": 2, "dueChapter": 5,
    })
    assert first.status_code == 200, first.text
    again = client.post("/api/projects/foreshadow", params={"dir": str(root)}, json={
        "name": "后窗插销锈死", "plantedChapter": 6, "dueChapter": 9,
    })
    assert again.status_code == 400
    assert "已有伏笔" in again.text


def test_generate_foreshadows_skips_rewritten_line(tmp_path, monkeypatch):
    """同层级、埋收章几乎重合、名字四成字重合 → 视为同一条线，不再入账。"""
    from app.domain import foreshadow_gen

    root = make_book(tmp_path)
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["worldText"] = "末日第七年，庇护所。"
    project["outlineText"] = "### 第1卷 名单（第1-30章）\n周砚管点名册。"
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (root / "ledger/foreshadow.jsonl").write_text(json.dumps({
        "id": "fs-old", "name": "后窗插销锈死", "kind": "detail",
        "plantedChapter": 2, "dueChapter": 5, "status": "open",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = "\n".join([
        "名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃",
        "后窗插销被人从外面焊过|细节|地点·登记室|3|拍1 擦窗推不动|6|赵婶|唯一退路失效|再擦一次|窗被钉死",
        "医疗棚床位跳号|细节|地点·庇护所|8|拍2 查床|20|陆敏|七号床没人|再数一次|床位补齐",
    ])

    monkeypatch.setattr(foreshadow_gen, "chat", lambda messages, **kw: {
        "text": lines, "model": "m", "usage": {},
    })
    res = foreshadow_gen.generate_foreshadows(root)

    assert res["count"] == 1
    names = [r["name"] for r in foreshadow_gen.fold_foreshadow(
        foreshadow_gen.read_jsonl(root / "ledger/foreshadow.jsonl"))]
    assert "后窗插销被人从外面焊过" not in names
    assert "医疗棚床位跳号" in names


def test_rewrite_prompt_carries_platform_playbook(tmp_path, monkeypatch):
    root = make_book(tmp_path)
    seen: dict[str, object] = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 10}}

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
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 10}}

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


def _run_ai_check_with_gap(root: Path, monkeypatch) -> None:
    """跑一轮 AI 复检，留一条没过、原句还在正文里的条目。"""
    monkeypatch.setattr(review, "chat", lambda messages, **kw: ai_reply(messages, suggestions=[{
        "severity": "mid", "code": "motivation", "message": "这句不像季恒",
        "quote": "他把最后一颗螺丝拧紧", "hint": "改短",
    }]))
    res = review.ai_check_chapter(root, 1)
    assert any(f.get("source") == "ai" for f in res["findings"])


def test_rewrite_carries_ai_findings_without_client(tmp_path, monkeypatch):
    """按技能改写不靠前端带问题：这一轮复检没过的条目要从账本补进提示词。"""
    root = make_book(tmp_path)
    _run_ai_check_with_gap(root, monkeypatch)
    seen: dict[str, object] = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 10}}

    monkeypatch.setattr(review, "chat", fake)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={})
    assert r.status_code == 200, r.text
    user = next(m["content"] for m in seen["messages"] if m["role"] == "user")  # type: ignore[index]
    assert "这句不像季恒" in user
    assert "[mid·复检]" in user


def test_rewrite_skips_ai_findings_the_author_unticked(tmp_path, monkeypatch):
    """作者在弹窗里取消勾选的复检条目，后端补条目时不能再塞回去。"""
    root = make_book(tmp_path)
    _run_ai_check_with_gap(root, monkeypatch)
    seen: dict[str, object] = {}

    def fake(messages, **kwargs):
        seen["messages"] = messages
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 10}}

    monkeypatch.setattr(review, "chat", fake)
    r = client.post("/api/projects/chapters/1/rewrite", params={"dir": str(root)}, json={
        "dismissed": ["这句不像季恒"],
    })
    assert r.status_code == 200, r.text
    user = next(m["content"] for m in seen["messages"] if m["role"] == "user")  # type: ignore[index]
    assert "这句不像季恒" not in user


def test_current_ai_check_returns_carried_round(tmp_path, monkeypatch):
    """刷新页面后前端要把这一章进行中的复检结论捞回来，不重新问模型。"""
    root = make_book(tmp_path)
    empty = client.get("/api/projects/chapters/1/ai-check/current", params={"dir": str(root)}).json()
    assert empty == {"carried": False, "result": None}

    _run_ai_check_with_gap(root, monkeypatch)
    calls = {"n": 0}
    monkeypatch.setattr(review, "chat", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    body = client.get("/api/projects/chapters/1/ai-check/current", params={"dir": str(root)}).json()
    assert body["carried"] is True
    assert calls["n"] == 0
    assert any(f.get("message") == "这句不像季恒" for f in body["result"]["findings"])


def test_ai_check_asks_about_gone_characters_in_body(tmp_path, monkeypatch):
    """前情里已经死了的人在本章正文出现，复检要单独问一句有没有交代。"""
    root = make_book(tmp_path, LONG + "赵婶站在门口，朝塔上看。")
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    bible["characters"].append({
        "name": "赵婶", "status": "dead", "appearanceStatus": "active", "firstChapter": 1,
    })
    (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    seen: list[dict] = []

    def fake(messages, **kwargs):
        seen.extend(prompt_items(messages[-1]["content"]))
        return ai_reply(messages, fails={"gone-characters": {
            "quote": "赵婶站在门口", "note": "她已经死了", "hint": "改成回忆或删掉",
        }})

    monkeypatch.setattr(review, "chat", fake)
    res = review.ai_check_chapter(root, 1)

    gone = next(i for i in seen if i["id"] == "gone-characters")
    assert "赵婶已死亡" in gone["要求"]
    assert "回忆" in gone["要求"]
    finding = next(f for f in res["findings"] if f.get("checkId") == "gone-characters")
    assert finding["severity"] == "mid"
    assert finding["source"] == "ai"
    assert "已离场人物" in finding["message"] or "赵婶" in finding["message"]


def add_chapter(root: Path, number: int, title: str, text: str, summary: str = "") -> None:
    body = f"chapters/{number:03d}-{title}.md"
    (root / body).write_text(text, encoding="utf-8")
    idx = json.loads((root / "chapters/index.json").read_text(encoding="utf-8"))
    idx.append({
        "number": number, "title": title, "file": body, "chars": len(text),
        "summary": summary, "characters": [], "approved": False,
    })
    (root / "chapters/index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")


def test_check_chapter_flags_character_who_died_earlier(tmp_path):
    """写后核对：上一章账本里已经死了的人，这一章的记忆又记成在场。"""
    from app.domain.memory import append_memory

    root = make_book(tmp_path)
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    bible["characters"][0].update({
        "status": "dead", "statusAt": 1,
        "statusLog": [{"chapter": 1, "status": "dead", "note": "沉船"}],
    })
    (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    add_chapter(root, 2, "回塔", LONG)
    append_memory(root, {
        "kind": "chapter", "chapter": 2, "summary": "季恒回到塔下。",
        "characterStates": [{"who": "季恒", "status": "在场"}],
    })

    res = review.check_chapter(root, 2)
    hit = next(f for f in res["findings"] if f["code"] == "gone-character-active")
    assert hit["severity"] == "high"
    assert "季恒在第1章已经死亡" in hit["message"]


def test_rewrite_prompt_carries_chapter_evidence(tmp_path, monkeypatch):
    """改写要求带上「依据」：问题里的人，前面章节记忆里最近一次怎么写的。"""
    from app.domain.memory import append_memory

    root = make_book(tmp_path)
    add_chapter(root, 2, "回塔", LONG)
    append_memory(root, {
        "kind": "chapter", "chapter": 1,
        "summary": "季恒把最后一颗螺丝拧紧，塔顶的红灯亮起来。",
        "characters": ["季恒"],
    })
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(review, "chat", fake_chat)
    review.rewrite_chapter(root, 2, findings=[{
        "severity": "mid", "code": "logic", "message": "季恒怎么知道塔顶的红灯亮了",
        "hint": "补一句他怎么看见的", "source": "ai",
    }])

    prompt = seen["prompt"]
    assert "季恒怎么知道塔顶的红灯亮了" in prompt
    assert "依据：第1章「季恒把最后一颗螺丝拧紧" in prompt


def test_check_chapter_attaches_memory_evidence(tmp_path):
    """体检结果本身带依据：问题里点到的人，前面章记忆里最近一次怎么写的。"""
    from app.domain.memory import append_memory

    root = make_book(tmp_path)
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    bible["rules"] = [{"name": "季恒不能离开塔", "forbiddenKeywords": ["下塔"]}]
    (root / "bible.json").write_text(json.dumps(bible, ensure_ascii=False), encoding="utf-8")
    add_chapter(root, 2, "下塔", LONG + "他决定下塔。", summary="季恒下塔")
    append_memory(root, {
        "kind": "chapter", "chapter": 1, "summary": "季恒守在塔顶，一整夜没下塔。",
        "characters": ["季恒"],
    })

    res = review.check_chapter(root, 2)
    hit = next(f for f in res["findings"] if f["code"] == "hard-rule")
    assert hit["evidence"] == [{"chapter": 1, "text": "季恒守在塔顶，一整夜没下塔"}]


def test_paragraph_rewrite_fills_evidence_when_missing(tmp_path, monkeypatch):
    """段落改写只给问题不给依据时，自己回查章记忆补一句。"""
    from app.domain.memory import append_memory

    root = make_book(tmp_path)
    add_chapter(root, 2, "回塔", LONG)
    append_memory(root, {
        "kind": "chapter", "chapter": 1, "summary": "季恒守在塔顶，一整夜没下塔。",
        "characters": ["季恒"],
    })
    seen: dict = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return {"text": "改过的正文。" * 400, "model": "test-model", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(review, "chat", fake_chat)
    review.rewrite_paragraph(root, 2, 1, finding={
        "severity": "mid", "message": "季恒怎么忽然到了塔下，没交代",
    })
    assert "依据：第1章「季恒守在塔顶" in seen["prompt"]
