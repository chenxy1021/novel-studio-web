"""数据安全 + 质量补充：删除快照、章节版本、唯一「写到哪」、防改平、跨章复读。

全部在 tmp 目录里跑，不碰真实书架。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain import quality, review, writing
from app.domain.continuity import character_line
from app.domain.review import ChapterBlocked
from app.domain.metrics import flattening
from app.llm.routing import reasoning_for
from app.store import chapter as chapter_store
from app.store import projects_root
from app.store.paths import pad3


def make_book(tmp_path: Path, *, words: int = 1000) -> Path:
    root = tmp_path / "书"
    (root / "chapters").mkdir(parents=True)
    (root / "ledger").mkdir()
    (root / "project.json").write_text(json.dumps({
        "title": "安全测试书",
        "genre": "悬疑",
        "platform": "generic",
        "targetChapters": 10,
        "wordsPerChapter": words,
        "outlineText": "### 第1卷 起（第1-10章）\n老周与阿雾。",
        "worldText": "雾港没有对岸。",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "bible.json").write_text(json.dumps({
        "characters": [{"name": "老周", "want": "守住渡口"}],
        "rules": [],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "chapters/index.json").write_text("[]", encoding="utf-8")
    return root


def add_chapter(root: Path, n: int, text: str, title: str | None = None) -> dict:
    title = title or f"第{n}章"
    _, rel = chapter_store.write_chapter(root, n, title, text)
    entry = {
        "number": n, "title": title, "file": rel,
        "chars": len(text), "approved": False,
        "chapterVerdict": "pass", "characters": [],
    }
    chapter_store.add_to_index(root, entry)
    return entry


def test_projects_root_reads_env_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_NOVEL_HOME", str(tmp_path / "a"))
    assert projects_root() == tmp_path / "a"
    monkeypatch.setenv("DSH_NOVEL_HOME", str(tmp_path / "b"))
    assert projects_root() == tmp_path / "b"


def test_delete_book_snapshots_before_removing(tmp_path):
    from app.core.paths import delete_book

    root = make_book(tmp_path)
    result = delete_book(str(root), expect_title="安全测试书")
    assert not root.exists()
    snap = Path(result["snapshot"])
    assert snap.is_dir()
    assert (snap / "project.json").is_file()
    assert (snap / "bible.json").is_file()


def test_write_chapter_keeps_previous_version(tmp_path):
    root = make_book(tmp_path)
    add_chapter(root, 1, "第一版正文。" * 80)
    add_chapter(root, 1, "第二版正文。" * 80)
    versions = list((root / "chapters" / ".versions" / "001").glob("*.md"))
    assert len(versions) == 1
    assert "第一版正文" in versions[0].read_text(encoding="utf-8")


def test_overview_gate_follows_index_not_stale_project(tmp_path):
    from app.api import books

    root = make_book(tmp_path)
    for n in (1, 2, 3):
        add_chapter(root, n, ("正文。" * 200) + f"第{n}章")
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["gate"] = {"phase": "writing", "chapter": 2}  # 故意停旧
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    over = books.project_overview(str(root))
    assert over.writtenThrough == 3
    assert over.nextChapter == 4
    assert over.gate["chapter"] == 4

    # 补存档旧章也不能把「下一章」拉回第 2 章。
    out = review.archive_chapter(root, 1, force=True)
    assert out["nextChapter"] == 4
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["gate"]["chapter"] == 4


def test_archive_fallback_memory_only_records_debut_never_death(tmp_path):
    """没有 AI 章记忆时，补的摘要只带出场名单；不能凭空写死任何人。"""
    root = make_book(tmp_path)
    entry = add_chapter(root, 1, "正文。" * 300)
    entry["characters"] = ["老周"]
    chapter_store.add_to_index(root, entry)
    review.archive_chapter(root, 1, force=True)
    bible = json.loads((root / "bible.json").read_text(encoding="utf-8"))
    c = bible["characters"][0]
    assert c.get("firstChapter") == 1
    assert c.get("exitChapter") in (None, 0)
    assert c.get("status", "active") == "active"


def test_flattening_flags_uniform_rewrite():
    rich = (
        "雨从午后就没停。他把伞收在门外，水顺着伞骨滴到水泥地上。\n\n"
        "“你回来得晚。”里屋的人说。\n\n"
        "他停住。手指还按在开关上。\n\n"
        "老人看了他一眼，转身去倒水。"
    )
    flat = "改过的正文。" * 100
    assert len(flattening(rich, flat)) >= 2
    assert flattening(rich, rich) == []


def test_quality_reports_cross_chapter_repeats(tmp_path):
    root = make_book(tmp_path)
    phrase = "窗外的雨一直下个不停"
    for n in (1, 2):
        add_chapter(root, n, f"{phrase}。" * 3 + "别的。" * 100)
    add_chapter(root, 3, f"{phrase}。" * 3 + "第三章。" * 100)
    rows = quality.cross_chapter_repeats(root, 3)
    assert any(r["phrase"] and len(r["chapters"]) >= 2 for r in rows)


def test_quality_parses_beat_scene_function():
    rows = quality.scene_beats({"beats": ["老周→想守住渡口→船被扣→只能答应", "阿雾出场"]})
    assert rows[0]["ok"] is True and rows[0]["parts"] == 4
    assert rows[1]["ok"] is False


def test_voice_samples_render_in_character_line():
    line = character_line({
        "name": "老周", "voice": "话少，句子短",
        "voiceSamples": ["船不开。", "你走吧。"],
    })
    assert "口吻样例" in line and "船不开" in line


def test_reasoning_routing_defaults_and_override(monkeypatch):
    assert reasoning_for("blueprint") == "high"
    assert reasoning_for("prose") == "medium"
    assert reasoning_for("memory") == "none"
    monkeypatch.setenv("NOVEL_STUDIO_REASONING", json.dumps({"prose": "high", "memory": "bogus"}))
    assert reasoning_for("prose") == "high"
    assert reasoning_for("memory") == "none"  # 非法值忽略


def test_archive_blocks_on_memory_gap_unless_forced(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "1")
    root = make_book(tmp_path)
    add_chapter(root, 1, "正文。" * 300)
    with pytest.raises(ChapterBlocked) as err:
        review.archive_chapter(root, 1)
    assert "章记忆" in str(err.value)
    out = review.archive_chapter(root, 1, force=True)
    assert out["approved"] == 1


def test_best_of_n_picks_richer_draft(tmp_path, monkeypatch):
    root = make_book(tmp_path, words=400)
    project = json.loads((root / "project.json").read_text(encoding="utf-8"))
    project["reviewBatch"] = {"chapters": [1]}
    (root / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (root / "ledger/foreshadow.jsonl").write_text(json.dumps({
        "id": "f1", "name": "渡口灯", "kind": "detail", "status": "open",
        "plantedChapter": 1, "dueChapter": 5,
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "ledger/outline.jsonl").write_text(json.dumps({
        "chapter": 1, "title": "雨夜",
        "beats": ["老周→想守住渡口→船被扣→只能答应"],
        "openingState": "雨夜", "endingState": "答应出海",
        "pressure": {}, "mustInclude": [], "mustAvoid": [],
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    rich = (
        "雨从午后就没停。他把伞收在门外，水顺着伞骨滴到水泥地上，积了一小片。\n\n"
        "屋里没开灯。桌上有半碗凉掉的面，筷子横搭在碗沿，汤面结了一层薄油。他站着看了几秒，才伸手去摸墙上的开关。\n\n"
        "“你回来得晚。”里屋的人说。\n\n"
        "他停住。手指还按在开关上，塑料壳有一道裂纹，硌着指腹。\n\n"
        "“路上堵。”他说。\n\n"
        "“堵了三个钟头？”\n\n"
        "“嗯。”\n\n"
        "里屋没有声音。过了一会儿，椅子腿在地上拖了一下，门帘被掀开。老人披着外套出来，头发乱着，手里捏着一张折过很多次的纸。\n\n"
        "“这个，”老人把纸放在桌上，“你收好。”\n\n"
        "他没有接。纸的边缘起了毛，角上盖着半个褪色的章。窗外一辆车开过，车灯扫过桌面，那半个章亮了一下，又暗下去。\n\n"
        "“哪来的？”\n\n"
        "“你别问。”\n\n"
        "老人看了他一眼，转身去倒水。水壶很旧，壶嘴歪着，倒出来的水在杯底打转。老人没喝，把杯子推到他面前。\n\n"
        "“喝了就走。”老人说，“今晚别住这儿。”\n\n"
        "他端起杯子。水是温的。\n\n"
        "他喝了一口，水里有一点铁锈味。老人回到里屋，帘子落下，布料擦过门框。桌上的纸还在原处，折痕很深，像被人反复打开又合上。\n\n"
        "他伸手，把纸拿起来。里面只有一行字，墨色发灰，笔画细得几乎看不清。他读了两遍，把纸重新折好，塞进内袋，贴着胸口。\n\n"
        "雨声小了些。楼道里有人下楼，脚步一级一级，到门口停下。门缝底下透进来一线光，又灭了。他把杯子放回桌上，杯底和桌面碰出一声轻响。老人没有出来。"
    )
    flat = "改过的正文。" * 100
    replies = [flat, rich]

    def fake(messages, **kwargs):
        text = replies.pop(0) if replies else rich
        return {"text": text, "model": "t", "usage": {}, "reason": ""}

    monkeypatch.setattr(writing, "chat", fake)
    out = writing.generate_prose(root, number=1, candidates=2, overwrite=True)
    assert out["candidates"] == 2
    assert "雨从午后" in out["text"]
