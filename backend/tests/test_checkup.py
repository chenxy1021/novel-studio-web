"""切片 4：体检结构化 / 六类语义复检 / 按技能改写。全部离线 fake chat。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain import metrics, review

CLEAN = "他抬手，把灯关掉。她没有回头。\n\n灯灭了。\n\n她问：谁在外面？"
CLEAN_LONG = CLEAN * 100  # 超过长篇每章 1800 字硬下限，且不触发任何 AI 痕迹规则
GOOD_REWRITE = "改过的正文。" * 200  # 1000 个汉字


def make_book(
    tmp_path: Path,
    text: str = CLEAN,
    *,
    words: int = 600,
    rules: list[dict] | None = None,
    samples: list | None = None,
) -> Path:
    root = tmp_path / "书"
    (root / "chapters").mkdir(parents=True)
    (root / "ledger").mkdir()
    (root / "drafts").mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "切片四测试书", "genre": "测试", "platform": "generic",
        "targetChapters": 100, "currentChapter": 1, "wordsPerChapter": words,
        "gate": {"phase": "writing", "chapter": 2, "reason": "", "at": ""},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "季恒", "want": "把塔修好", "fear": "停播", "voice": "短句"}],
        "rules": rules or [],
        "style": {"samples": samples or []},
    }, ensure_ascii=False), encoding="utf-8")
    rel = "chapters/001-第一段广播.md"
    (root / rel).write_text(text, encoding="utf-8")
    (root / "chapters/index.json").write_text(json.dumps([{
        "number": 1, "title": "第一段广播", "file": rel,
        "chars": metrics.count_chars(text), "summary": "第一段广播。", "characters": ["季恒"],
        "approved": False, "chapterVerdict": "pass", "verdict": "良",
        "fixReasons": [], "dialogueRatio": 0.1,
    }], ensure_ascii=False), encoding="utf-8")
    return root


def fake_returning(text: str, seen: list[list[dict]] | None = None):
    def fake(messages, **kwargs):
        if seen is not None:
            seen.append(messages)
        return {"text": text, "model": "test-model", "usage": {"total_tokens": 10}}
    return fake


def paragraphs_of(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages)


# ------------------------------ 确定性定位 ------------------------------


def test_detect_ai_tells_paragraph_and_offset():
    p1 = "他皱了皱眉，她也皱了皱眉。"
    p2 = "空气仿佛凝固了，他又皱了皱眉。"
    text = p1 + "\n\n" + p2

    tells = metrics.detect_ai_tells(text)
    frown = next(t for t in tells if t["id"] == "eyebrow-frown")
    assert frown["count"] == 3
    samples = frown["samples"]
    assert [s["paragraph"] for s in samples] == [1, 1, 2]
    assert [s["offset"] for s in samples] == [p1.find("皱了皱眉"), p1.rfind("皱了皱眉"), p2.find("皱了皱眉")]
    assert [s["line"] for s in samples] == [1, 1, 3]

    air = next(t for t in tells if t["id"] == "air-froze")
    assert air["samples"][0]["paragraph"] == 2
    assert air["samples"][0]["offset"] == 0


def test_text_hash_normalizes_newlines_and_edges():
    a = metrics.text_hash("第一段。\r\n\r\n第二段。\n")
    b = metrics.text_hash("  第一段。\n\n第二段。  ")
    assert a == b
    assert len(a) == 16


# ------------------------------ 结构化体检 ------------------------------


def test_check_chapter_exposes_ai_tells_rules_and_skills(tmp_path):
    body = "空气仿佛凝固了，他皱了皱眉。" * 40
    root = make_book(tmp_path, body)
    result = review.check_chapter(root, 1)

    assert "findings" in result  # 兼容旧字段
    ai = result["aiTells"]
    assert ai["level"] == result["verdict"]["level"]
    assert ai["total"] == sum(c["count"] for c in ai["categories"])
    assert ai["density"] == result["verdict"]["density"]
    cat = next(c for c in ai["categories"] if c["id"] == "eyebrow-frown")
    assert {"id", "label", "severity", "count", "per1000", "samples"} <= set(cat)
    assert {"text", "paragraph", "offset", "line"} <= set(cat["samples"][0])

    rule_ids = {r["id"] for r in result["rules"]}
    assert {"chars", "dialogue", "endHook"} <= rule_ids
    assert all(r["state"] in ("ok", "warn", "bad") for r in result["rules"])

    assert result["textHash"] == metrics.text_hash(body)
    assert len(result["textHash"]) == 16
    assert result["checkedAt"].endswith("Z")
    assert "deai" in result["suggestedSkills"]


def test_check_chapter_clean_book_suggests_conservative_combo(tmp_path):
    root = make_book(tmp_path, CLEAN_LONG)
    result = review.check_chapter(root, 1)
    assert result["aiTells"]["total"] == 0
    assert {"deai", "continuity"} <= set(result["suggestedSkills"])


def test_check_chapter_hard_rule_becomes_rule_row(tmp_path):
    root = make_book(tmp_path, CLEAN, rules=[{"name": "禁刀", "forbiddenKeywords": ["刀"]}])
    (root / "chapters/001-第一段广播.md").write_text(CLEAN + "\n\n他握着刀。", encoding="utf-8")
    result = review.check_chapter(root, 1)
    hard = [r for r in result["rules"] if r["id"] == "hardRule"]
    assert hard and hard[0]["state"] == "bad" and "禁刀" in hard[0]["limit"]
    assert "continuity" in result["suggestedSkills"]


# ------------------------------ 六类语义复检 ------------------------------


def test_ai_check_groups_six_categories(tmp_path, monkeypatch):
    root = make_book(tmp_path, CLEAN)
    payload = [
        {"severity": "mid", "code": "dialogue", "message": "对话在复述信息",
         "quote": "她问：谁在外面？", "hint": "删一轮"},
        {"severity": "mid", "code": "repetition", "message": "钥匙来历说了三次",
         "quote": "灯灭了。", "hint": "只留一次"},
        {"severity": "high", "code": "emotion-summary", "message": "五味杂陈没落到动作",
         "quote": "她没有回头。", "hint": "写动作"},
        {"severity": "mid", "code": "unknown-code", "message": "不明分类",
         "quote": "他抬手，把灯关掉。", "hint": ""},
    ]
    monkeypatch.setattr(review, "chat", fake_returning(json.dumps(payload, ensure_ascii=False)))

    result = review.ai_check_chapter(root, 1)
    assert [g["code"] for g in result["groups"]] == [
        "continuity", "motivation", "voice", "dialogue", "repetition", "emotion-summary",
    ]
    by_code = {g["code"]: g for g in result["groups"]}
    assert by_code["dialogue"]["count"] == 1
    assert by_code["repetition"]["count"] == 1
    assert by_code["emotion-summary"]["count"] == 1
    assert by_code["voice"]["count"] == 1  # 非法 code 归口吻
    assert by_code["continuity"]["count"] == 0  # 无问题也保留 0 条组
    assert by_code["emotion-summary"]["findings"][0]["group"] == "emotion-summary"

    ai_findings = [f for f in result["findings"] if f.get("source") == "ai"]
    assert len(ai_findings) == 4
    assert all(f["group"] in by_code for f in ai_findings)
    # 语义层回包仍带确定性层，前端面板不会在复检后丢掉分类与定位。
    assert set(result["aiTells"]) >= {"level", "total", "density", "categories"}
    assert isinstance(result["rules"], list)
    assert result["textHash"]
    assert isinstance(result["suggestedSkills"], list)
    assert any(f["code"] == "unknown-code" for f in result["findings"])  # 旧字段保留原 code


# ------------------------------ 按技能改写 ------------------------------


def test_rewrite_explicit_skills_inject_prompt_modules(tmp_path, monkeypatch):
    root = make_book(tmp_path, CLEAN)
    seen: list[list[dict]] = []
    monkeypatch.setattr(review, "chat", fake_returning(GOOD_REWRITE, seen))

    result = review.rewrite_chapter(root, 1, skills=["deai", "dialogue"])
    prompt = paragraphs_of(seen[-1])
    assert result["skills"] == ["deai", "dialogue"]
    assert "【技能：去 AI 味】" in prompt and "# 人味改写" in prompt
    assert "【技能：对话打磨】" in prompt and "# 对话写作" in prompt
    assert "平台打法" in prompt


def test_rewrite_defaults_to_suggested_skills(tmp_path, monkeypatch):
    root = make_book(tmp_path, CLEAN_LONG)
    seen: list[list[dict]] = []
    monkeypatch.setattr(review, "chat", fake_returning(GOOD_REWRITE, seen))

    suggested = review.check_chapter(root, 1)["suggestedSkills"]
    result = review.rewrite_chapter(root, 1)
    prompt = paragraphs_of(seen[-1])
    assert result["skills"] == suggested
    assert {"deai", "continuity"} <= set(result["skills"])
    assert "【技能：去 AI 味】" in prompt
    assert "【技能：连续性检查】" in prompt


@pytest.mark.parametrize(
    ("prose", "words", "rules", "fragment"),
    [
        ("短。" * 20, 600, None, "过短"),
        ("改过的正文。" * 60, 600, None, "75%"),
        ("他握住了刀。" * 100, 600, [{"name": "禁刀", "forbiddenKeywords": ["刀"]}], "撞规则"),
    ],
)
def test_rewrite_guards_keep_old_text(tmp_path, monkeypatch, prose, words, rules, fragment):
    root = make_book(tmp_path, CLEAN, words=words, rules=rules)
    chapter = root / "chapters/001-第一段广播.md"
    before = chapter.read_text(encoding="utf-8")
    monkeypatch.setattr(review, "chat", fake_returning(prose))

    with pytest.raises(review.ReviewError) as err:
        review.rewrite_chapter(root, 1)
    assert fragment in str(err.value)
    assert chapter.read_text(encoding="utf-8") == before
    assert list((root / "drafts").iterdir()) == []


def test_rewrite_success_moves_old_draft_and_reports_before_after(tmp_path, monkeypatch):
    root = make_book(tmp_path, CLEAN)
    monkeypatch.setattr(review, "chat", fake_returning(GOOD_REWRITE))

    result = review.rewrite_chapter(root, 1, skills=["deai", "continuity"])
    assert result["chapter"]["approved"] is False
    assert result["oldChars"] == metrics.count_chars(CLEAN)
    assert result["newChars"] == metrics.count_chars(GOOD_REWRITE)
    assert set(result["aiTellsBefore"]) == {"total", "level", "density"}
    assert set(result["aiTellsAfter"]) == {"total", "level", "density"}
    assert result["chars"] == result["newChars"]
    assert result["check"]["textHash"] == metrics.text_hash(GOOD_REWRITE)

    drafts = list((root / "drafts").iterdir())
    assert len(drafts) == 1 and "rewrite" in drafts[0].name
    assert drafts[0].read_text(encoding="utf-8") == CLEAN

    rows = review.list_discarded(root)
    assert any("rewrite" in r["draftFile"] for r in rows)
    ledger = [json.loads(line) for line in (root / "ledger/review.jsonl").read_text(encoding="utf-8").splitlines()]
    rewrite_row = next(r for r in ledger if r["kind"] == "rewrite")
    assert rewrite_row["skills"] == ["deai", "continuity"]


def test_rewrite_route_passes_skill_selection(tmp_path, monkeypatch):
    """路由必须把作者勾的技能和补充要求送到领域层，不能只走后端预选。"""
    from fastapi.testclient import TestClient

    from app.main import app

    root = make_book(tmp_path, CLEAN)
    seen: dict = {}

    def fake_rewrite(_root, _number, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "skills": kwargs.get("skills") or []}

    monkeypatch.setattr(review, "rewrite_chapter", fake_rewrite)
    got = TestClient(app).post(
        "/api/projects/chapters/1/rewrite",
        params={"dir": str(root)},
        json={"skills": ["deai", "dialogue"], "instruction": "只改第 3 段"},
    )
    assert got.status_code == 200, got.text
    assert seen["skills"] == ["deai", "dialogue"]
    assert seen["instruction"] == "只改第 3 段"
