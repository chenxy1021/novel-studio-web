"""组织架构 / 章脉 / 相关章节 / 滚动规划 / 审美复检 / 回灌 / 导出。"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain import (
    aesthetic,
    chapter_graph,
    create,
    export,
    hierarchy,
    memory,
    related,
    review,
    rolling,
    sync,
)
from app.store import (
    add_to_index,
    append_jsonl,
    load_bible,
    load_project,
    project_path,
    read_index,
    save_bible,
    save_project,
    write_index,
)
from app.store.chapter import text_hash


def _book(tmp_path: Path, **kw) -> Path:
    title = kw.pop("title", "结构测试")
    books = tmp_path / "books"
    books.mkdir(exist_ok=True)
    old = create.books_root
    create.books_root = lambda: books
    try:
        return Path(create.create_book(title=title, **kw)["dir"])
    finally:
        create.books_root = old


def _seed(root: Path, **bible) -> None:
    save_bible(root, {**load_bible(root), **bible})


def _chapter(root: Path, n: int, title: str, text: str) -> dict:
    d = project_path(root, "chapters")
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{n:03d}-{title}.md").write_text(text + "\n", encoding="utf-8")
    entry = review._entry_from_text({
        "number": n, "title": title, "file": f"chapters/{n:03d}-{title}.md",
    }, text)
    add_to_index(root, entry)
    return entry


def _mem(root: Path, n: int, **row) -> None:
    append_jsonl(project_path(root, "ledger/memory.jsonl"), {
        "kind": "chapter", "chapter": n, "title": f"第{n}章",
        "summary": row.pop("summary", f"第{n}章的摘要"), **row,
    })


def _foreshadow(root: Path, fid: str, name: str, planted: int, due: int, payoff: int = 0) -> None:
    append_jsonl(project_path(root, "ledger/foreshadow.jsonl"), {
        "id": fid, "name": name, "kind": "detail",
        "plantedChapter": planted, "dueChapter": due,
    })
    if payoff:
        append_jsonl(project_path(root, "ledger/foreshadow.jsonl"), {
            "id": fid, "op": "payoff", "payoffChapter": payoff,
        })


# --------------------------------------------------------------------------- #
# 组织架构 / 职业等级
# --------------------------------------------------------------------------- #


def test_hierarchy_view_resolves_parents_and_warns(tmp_path):
    root = _book(tmp_path)
    _seed(root,
          characters=[{"name": "老周"}, {"name": "阿雾"}],
          organizations=[
              {"name": "船行会", "kind": "行会", "leader": "老周",
               "members": [{"name": "阿雾", "role": "账房"}, {"name": "路人甲", "role": "船工"}]},
              {"name": "夜航队", "kind": "小队", "parent": "船行会"},
              {"name": "断头会", "kind": "小队", "parent": "不存在的上级"},
          ],
          careers=[{"name": "船工位阶", "levels": [{"name": "学徒"}, {"name": "掌舵"}]}])

    view = hierarchy.hierarchy_view(root)
    assert view["counts"] == {"organizations": 3, "careers": 1}
    night = next(o for o in view["organizations"] if o["name"] == "夜航队")
    assert night["parentId"] == 0
    member = next(m for m in view["organizations"][0]["members"] if m["name"] == "路人甲")
    assert member["known"] is False
    assert any("路人甲" in w for w in view["warnings"])
    assert any("不存在的上级" in w for w in view["warnings"])


def test_hierarchy_view_breaks_cycles(tmp_path):
    root = _book(tmp_path)
    _seed(root, organizations=[
        {"name": "甲", "parent": "乙"},
        {"name": "乙", "parent": "甲"},
    ])
    view = hierarchy.hierarchy_view(root)
    assert any("成环" in w for w in view["warnings"])
    assert any(o["parentId"] is None for o in view["organizations"])


def test_generate_hierarchy_fills_without_overwriting(tmp_path, monkeypatch):
    root = _book(tmp_path)
    _seed(root,
          characters=[{"name": "老周"}],
          organizations=[{"name": "船行会", "summary": "作者自己写的"}])

    payload = {
        "organizations": [
            {"name": "船行会", "kind": "行会", "summary": "模型写的", "members": [{"name": "老周", "role": "会长"}]},
            {"name": "夜航队", "kind": "小队", "parent": "船行会"},
        ],
        "careers": [{"name": "船工", "levels": [{"name": "学徒"}, {"name": "掌舵"}]}],
    }
    monkeypatch.setattr(hierarchy, "chat", lambda *a, **k: {"text": json.dumps(payload), "model": "fake"})

    out = hierarchy.generate_hierarchy(root)
    bible = load_bible(root)
    org = next(o for o in bible["organizations"] if o["name"] == "船行会")
    assert org["summary"] == "作者自己写的"  # 不覆盖
    assert org["kind"] == "行会"            # 只补空字段
    assert org["members"][0]["name"] == "老周"
    assert out["added"] == {"organizations": 1, "careers": 1}
    assert any(c["name"] == "船工" for c in bible["careers"])


# --------------------------------------------------------------------------- #
# 章节图谱 + 相关章节
# --------------------------------------------------------------------------- #


def test_chapter_graph_builds_cast_and_foreshadow_edges(tmp_path):
    root = _book(tmp_path)
    for n in (1, 2, 5):
        _chapter(root, n, f"第{n}章", f"正文{n}。" * 50)
    _mem(root, 1, characters=["老周", "阿雾"])
    _mem(root, 2, characters=["老周", "阿雾"])
    _mem(root, 5, characters=["老周"])
    _foreshadow(root, "f1", "断桨", 1, 5, payoff=5)

    graph = chapter_graph.build_chapter_graph(root)
    assert [n["number"] for n in graph["nodes"]] == [1, 2, 5]
    kinds = {(e["from"], e["to"], e["kind"]) for e in graph["edges"]}
    assert (1, 2, "cast") in kinds
    assert (1, 5, "foreshadow") in kinds
    fs = next(e for e in graph["edges"] if e["kind"] == "foreshadow")
    assert fs["status"] == "paid"
    assert graph["stats"]["paidForeshadows"] == 1


def test_related_chapters_scores_cast_and_recency(tmp_path):
    root = _book(tmp_path, target_chapters=30)
    for n in (1, 2, 5):
        _chapter(root, n, f"第{n}章", f"正文{n}。" * 50)
    _mem(root, 1, characters=["老周", "阿雾"], summary="老周和阿雾在码头")
    _mem(root, 2, characters=["老周"], summary="老周一个人守夜")
    _mem(root, 5, characters=["阿雾"], summary="阿雾回到码头")
    _foreshadow(root, "f1", "断桨", 2, 8)

    rows = related.related_chapters(root, 6, limit=5)
    assert rows
    top = rows[0]
    assert top["number"] == 5  # 最近 + 同卷 + 人物
    assert top["reasons"]
    assert any(r["number"] == 2 and any("伏笔" in x for x in r["reasons"]) for r in rows)


# --------------------------------------------------------------------------- #
# 滚动规划
# --------------------------------------------------------------------------- #


def test_rolling_status_and_compass(tmp_path):
    root = _book(tmp_path, target_chapters=30)
    _chapter(root, 1, "第一章", "正文。" * 60)
    rolling.set_compass(root, "主角要拿回名字；不能死而复生")
    status = rolling.rolling_status(root)
    assert status["writtenThrough"] == 1
    assert status["nextChapter"] == 2
    assert "名字" in status["compassText"]
    assert load_project(root)["compassText"].startswith("主角")


def test_rolling_plan_appends_volume_and_outlines(tmp_path, monkeypatch):
    root = _book(tmp_path, target_chapters=30)
    project = load_project(root)
    project["outlineText"] = "### 第1卷 上（第1-2章）\n- 任务：起\n- 卷末钩子：疑\n"
    save_project(root, project)
    memory.refresh_volumes(root)
    _chapter(root, 1, "第一章", "正文。" * 60)
    _chapter(root, 2, "第二章", "正文。" * 60)

    block = "### 第2卷 下（第3-8章）\n- 任务与矛盾：接着往下\n- 卷内节拍：一拍两拍三拍\n- 卷末钩子：悬念\n" + "补充。" * 40
    monkeypatch.setattr(rolling, "chat", lambda *a, **k: {"text": block, "model": "fake"})
    monkeypatch.setattr(rolling, "generate_outlines", lambda *a, **k: {
        "ok": True, "from": 3, "to": 7, "outlines": [{"chapter": n} for n in range(3, 8)],
        "spine": "", "reused": False, "model": "fake",
    })

    out = rolling.rolling_plan(root, chapters=5)
    assert out["volumeAdded"]["text"].startswith("### 第2卷")
    assert out["from"] == 3 and out["to"] == 7
    assert "第2卷 下" in load_project(root)["outlineText"]
    assert len(out["volumes"]) == 2


# --------------------------------------------------------------------------- #
# 审美复检
# --------------------------------------------------------------------------- #


def test_aesthetic_check_persists_and_marks_stale(tmp_path, monkeypatch):
    root = _book(tmp_path)
    _chapter(root, 3, "夜航", "老周把断桨靠在门边。他数了三遍缆绳。" * 20)
    payload = {
        "dimensions": [
            {"key": "wording", "score": 4, "quote": "把断桨靠在门边", "comment": "动作具体", "fix": "保留"},
            {"key": "rhythm", "score": 3, "quote": "他数了三遍缆绳", "comment": "稳", "fix": "缩短第三段"},
            {"key": "dialogue", "score": 1, "quote": "", "comment": "无对话", "fix": "加一句"},
            {"key": "imagery", "score": 4, "quote": "靠在门边", "comment": "能看见", "fix": "保留"},
            {"key": "emotion", "score": 3, "quote": "数了三遍", "comment": "克制", "fix": "加代价"},
        ],
        "summary": "画面好，对话缺",
    }
    monkeypatch.setattr(aesthetic, "chat", lambda *a, **k: {"text": json.dumps(payload), "model": "fake"})

    out = aesthetic.aesthetic_check(root, 3)
    assert out["average"] == 3.0
    assert [d["key"] for d in out["dimensions"]] == [k for k, _, _ in aesthetic.DIMENSIONS]
    assert aesthetic.rating(root, 3)["stale"] is False

    # 正文改了但没复检：旧评语标记过期。
    path = project_path(root, "chapters") / "003-夜航.md"
    path.write_text("换了一段全新的正文。\n", encoding="utf-8")
    assert aesthetic.rating(root, 3)["stale"] is True


# --------------------------------------------------------------------------- #
# 手改回灌
# --------------------------------------------------------------------------- #


def test_sync_scan_detects_edited_and_untracked(tmp_path):
    root = _book(tmp_path)
    _chapter(root, 1, "第一章", "旧正文。" * 40)
    path = project_path(root, "chapters") / "001-第一章.md"
    path.write_text("新正文。" * 45 + "\n", encoding="utf-8")
    d = project_path(root, "chapters")
    (d / "002-手写第二章.md").write_text("复制进来的稿子。" * 30 + "\n", encoding="utf-8")

    scan = sync.scan_sync(root)
    kinds = {x["number"]: x["kind"] for x in scan["items"]}
    assert kinds[1] == "edited"
    assert kinds[2] == "untracked"
    assert scan["counts"]["edited"] == 1


def test_sync_apply_updates_index_and_memory(tmp_path, monkeypatch):
    root = _book(tmp_path)
    _chapter(root, 1, "第一章", "旧正文。" * 40)
    _mem(root, 1, characters=["老周"], summary="旧摘要")
    path = project_path(root, "chapters") / "001-第一章.md"
    new_text = "新正文。" * 45
    path.write_text(new_text + "\n", encoding="utf-8")

    calls: list[int] = []

    def fake_memory(root_path, n, **kw):
        calls.append(n)
        append_jsonl(project_path(root_path, "ledger/memory.jsonl"), {
            "kind": "chapter", "chapter": n, "summary": "新摘要",
            "characters": ["老周"], "sha256": text_hash(new_text),
        })
        return {"chapter": n, "summary": "新摘要"}

    monkeypatch.setattr(sync, "generate_chapter_memory", fake_memory)

    out = sync.apply_sync(root, regenerate_memory=True)
    assert out["applied"] == [1]
    assert calls == [1]
    entry = next(e for e in read_index(root) if e["number"] == 1)
    assert entry["sha256"] == text_hash(new_text)
    assert sync.scan_sync(root)["items"] == []
    assert memory.load_memory_rows(root)["byChapter"][1]["summary"] == "新摘要"


def test_sync_baseline_only_records_fingerprint(tmp_path, monkeypatch):
    root = _book(tmp_path)
    entry = _chapter(root, 1, "第一章", "正文。" * 40)
    rows = read_index(root)
    rows[0].pop("sha256", None)
    write_index(root, rows)
    _mem(root, 1, summary="已有记忆")

    called: list[int] = []
    monkeypatch.setattr(sync, "generate_chapter_memory", lambda *a, **k: called.append(1))
    out = sync.apply_sync(root, regenerate_memory=True)
    assert out["applied"] == [1]
    assert called == []  # 旧书只补基线，不重跑记忆
    fresh = read_index(root)[0]
    assert fresh["sha256"] == text_hash("正文。" * 40)
    assert entry["number"] == 1


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #


def test_export_txt_orders_chapters_and_reports_gaps(tmp_path):
    root = _book(tmp_path, title="导出测试", logline="一句话")
    _chapter(root, 1, "夜航", "第一段。\n\n第二段。")
    _chapter(root, 5, "返航", "第五章正文。")

    out = export.export_txt(root)
    assert out["chapters"] == 2
    assert out["firstChapter"] == 1 and out["lastChapter"] == 5
    assert out["gaps"] == ["2-4"]
    path = project_path(root, "exports") / out["filename"]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("导出测试")
    assert "第1章 夜航" in text
    assert "第5章 返航" in text
    assert text.index("第1章 夜航") < text.index("第5章 返航")
