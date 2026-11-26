"""AI 选题：章节数/字数必填，书名和简介都跟着选题由模型生成。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import concepts, create
from app.main import app

client = TestClient(app)

FAKE = {
    "text": json.dumps([
        {
            "title": "最后一班渡船", "titleOptions": ["渡口无灯", "夜航船"],
            "genre": "悬疑·民俗", "oneLine": "渡船每夜多载一个不存在的人。",
            "synopsis": "摆渡人老周守着一座没有对岸的渡口。" * 8,
            "hitRate": "high", "hitReason": "开局就有诡事，适合短章追读。",
            "differentiation": "同类写鬼渡→我写渡的是活人的债。",
            "risk": "中段容易变成单元剧。",
        },
        {
            "title": "我在末日卖明天", "titleOptions": ["明天期货", "末日交易所"],
            "genre": "科幻·末世", "oneLine": "末日里，最贵的商品是别人的明天。",
            "synopsis": "灾变后人类只能活到当天，主角发现自己能借来别人的明天。" * 8,
            "hitRate": "mid", "hitReason": "设定强，但需要稳住规则。",
            "differentiation": "同类囤物资→我写时间交易。",
            "risk": "规则写崩就失去张力。",
        },
    ], ensure_ascii=False),
    "model": "test-model",
}


NUWEN_FAKE = {
    "text": json.dumps([{
        "title": "她死那天全城放晴",
        "titleOptions": ["放晴", "头七无雨"],
        "genre": "都市·情感",
        "oneLine": "他替她挡了一辈子雨，最后亲手关了她的伞。",
        "synopsis": "沈砚把林晚秋从雨里捡回来，给她撑了十年伞。" * 6,
        "hitRate": "high",
        "hitReason": "反转贴着最珍视的东西落地。",
        "differentiation": "同类写深情守护→我写守护本身成了杀死她的原因。",
        "risk": "中段若只写误会，会变成狗血。",
        "nuewen": {
            "most": "那把旧黑伞，和每天六点在校门口等她",
            "turns": ["他为救公司签下拆迁书→她的旧居被推平", "他瞒下病情想陪她过完生日→她撞见他安排后事"],
            "witness": "她的弟弟，站在两块墓碑前",
            "chain": "他每一次保护都在剥夺她的选择，最后她替他做了选择。",
        },
    }], ensure_ascii=False),
    "model": "test-model",
}


def _fake_chat(messages, **kwargs):
    return FAKE


def test_concepts_require_chapters_and_words(monkeypatch):
    monkeypatch.setattr(concepts, "chat", _fake_chat)
    r = client.post("/api/projects/concepts", json={
        "direction": "民俗悬疑", "targetChapters": 0, "wordsPerChapter": 3000,
    })
    assert r.status_code == 400
    assert "章节数" in r.json()["detail"]

    r = client.post("/api/projects/concepts", json={
        "direction": "民俗悬疑", "targetChapters": 100, "wordsPerChapter": 0,
    })
    assert r.status_code == 400
    assert "字数" in r.json()["detail"]


def test_concepts_returns_clean_candidates(monkeypatch, tmp_path):
    seen: list[list[dict]] = []

    def fake(messages, **kwargs):
        seen.append(messages)
        return FAKE

    monkeypatch.setattr(concepts, "chat", fake)
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)

    r = client.post("/api/projects/concepts", json={
        "direction": "民俗悬疑",
        "targetChapters": 120,
        "wordsPerChapter": 3000,
        "count": 3,
        "avoid": ["旧选题｜悬疑｜老梗"],
    })
    assert r.status_code == 200, r.text
    rows = r.json()["concepts"]
    assert [c["title"] for c in rows] == ["最后一班渡船", "我在末日卖明天"]
    assert rows[0]["hitRate"] == "high"
    assert rows[0]["platform"] == "通用"
    prompt = "\n".join(m["content"] for m in seen[0])
    assert "民俗悬疑" in prompt
    assert "120 章" in prompt
    assert "旧选题" in prompt
    assert "书名：由你根据选题自己起" in prompt
    assert "题材约束" in prompt
    assert "必须给满 3 个" in prompt


def test_nuewen_mode_uses_formula_and_returns_structure(monkeypatch):
    seen: list[list[dict]] = []

    def fake(messages, **kwargs):
        seen.append(messages)
        return NUWEN_FAKE

    monkeypatch.setattr(concepts, "chat", fake)
    r = client.post("/api/projects/concepts", json={
        "genre": "都市情感",
        "targetChapters": 120,
        "wordsPerChapter": 3000,
        "nuewen": True,
    })
    assert r.status_code == 200, r.text
    concept = r.json()["concepts"][0]
    assert concept["nuewen"]["most"].startswith("那把旧黑伞")
    assert len(concept["nuewen"]["turns"]) == 2
    prompt = "\n".join(m["content"] for m in seen[0])
    assert "虐文" in prompt
    assert "最想活的死" in prompt
    assert "先虐后爽" in prompt
    assert '"nuewen"' in prompt


def test_create_book_keeps_concept_history(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "books_root", lambda: tmp_path)
    r = client.post("/api/projects/create", json={
        "title": "最后一班渡船",
        "genre": "悬疑·民俗",
        "platform": "fanqie",
        "targetChapters": 120,
        "wordsPerChapter": 3000,
        "logline": "渡船每夜多载一个不存在的人。",
        "synopsis": "摆渡人老周守着一座没有对岸的渡口。",
        "concepts": [{"id": "c1", "title": "最后一班渡船"}, {"id": "c2", "title": "夜航船"}],
        "selectedConceptId": "c1",
        "nuewen": True,
    })
    assert r.status_code == 200, r.text
    root = Path(r.json()["book"]["dir"])
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in project["concepts"]] == ["c1", "c2"]
    assert project["selectedConceptId"] == "c1"
    assert project["concept"]["title"] == "最后一班渡船"
    assert project["nuewen"] is True


def test_extract_json_repairs_unescaped_quotes():
    """模型在 synopsis 里写 "养液"，不是合法 JSON；解析要能救回来。"""
    raw = '''[
      {"title": "最后一口", "oneLine": "她能变出食物，却饿死在粮仓中央。",
       "synopsis": "沈鹿的异能是把液体凝成"养液"，喝一口顶三天。", "genre": "末世"}
    ]'''
    payload = concepts._extract_json(raw)
    assert payload and payload[0]["title"] == "最后一口"
    assert "养液" in payload[0]["synopsis"]


def test_generate_concepts_tolerates_inner_quotes(monkeypatch):
    broken = {
        "text": '''[{"title":"最后一口","oneLine":"她能变出食物。",
                  "synopsis":"她把液体凝成"养液"，分给全城。","genre":"末世"}]''',
        "model": "test-model",
    }
    monkeypatch.setattr(concepts, "chat", lambda messages, **kwargs: broken)
    out = concepts.generate_concepts(target_chapters=80, words_per_chapter=2000, count=1)
    assert out["concepts"][0]["title"] == "最后一口"
    assert "养液" in out["concepts"][0]["synopsis"]


def test_concepts_stream_emits_reason_and_output(monkeypatch):
    """模型不吐 reasoning_content 时，正文增量也要推给前端，不能一直空白。"""
    text = json.dumps([{
        "title": "最后一口", "genre": "末世",
        "oneLine": "她能变出食物，却饿死在粮仓中央。",
        "synopsis": "沈鹿把液体凝成「养液」，分给全城。" * 5,
    }], ensure_ascii=False)

    def fake(messages, **kwargs):
        kwargs["on_reason"]("先想一个反差点。")
        kwargs["on_delta"](text)
        return {"text": text, "reason": "先想一个反差点。", "model": "t", "usage": {}}

    monkeypatch.setattr(concepts, "chat", fake)
    r = client.post("/api/projects/concepts/stream", json={
        "targetChapters": 80, "wordsPerChapter": 2000, "count": 1,
    })
    assert r.status_code == 200
    events = [
        json.loads(line[5:].strip())
        for line in r.text.splitlines() if line.startswith("data:")
    ]
    kinds = [e["type"] for e in events]
    assert "reason" in kinds and "delta" in kinds and kinds[-1] == "done"
    assert events[-1]["result"]["concepts"][0]["title"] == "最后一口"
