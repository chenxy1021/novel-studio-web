"""段落纲：plan / list / chapterFromSegment 与写盘/重叠/删除/非法范围的错误文案。
"""

from pathlib import Path

import pytest

from app.domain import create, segment
from app.store import save_bible


@pytest.fixture
def book(tmp_path) -> Path:
    books = tmp_path / "books"
    books.mkdir()
    old = create.books_root
    create.books_root = lambda: books
    try:
        root = Path(create.create_book(title="段落测试", target_chapters=30)["dir"])
    finally:
        create.books_root = old
    save_bible(root, {
        "characters": [{"name": "老周", "importance": "核心", "want": "守住渡口"}],
        "rules": [{"name": "不能回头"}],
        "locations": [{"name": "渡口"}],
    })
    return root


def test_write_overlap_list_delete(book):
    assert segment.write_segment_outline(book, segment.plan_segment(book, frm=1, to=10)) == {
        "ok": True, "from": 1, "to": 10, "stages": 3,
    }
    with pytest.raises(ValueError, match="与已有批次第1-10章重叠"):
        segment.write_segment_outline(book, segment.plan_segment(book, frm=5, to=14))
    assert [(s["from"], s["to"]) for s in segment.list_segments(book)] == [(1, 10)]
    # 合成书还没写正文，删除时 written 只统计已写章。
    assert segment.delete_segment(book, frm=1, to=10) == {"ok": True, "from": 1, "to": 10, "written": 0}
    assert segment.list_segments(book) == []
    assert segment.get_segment(book, frm=3) is None


def test_rejects_bad_input(book):
    with pytest.raises(ValueError, match="stages 必须按顺序完整覆盖"):
        segment.write_segment_outline(book, {"from": 20, "to": 25, "stages": [{"chapters": [20, 22]}]})
    with pytest.raises(ValueError, match="没有第 20-25 章的段落纲"):
        segment.delete_segment(book, frm=20, to=25)
    with pytest.raises(ValueError, match="需要 from"):
        segment.plan_segment(book, frm=0)
    with pytest.raises(ValueError, match="一段最多 30 章"):
        segment.plan_segment(book, frm=1, to=40)
    with pytest.raises(ValueError, match="必须是 ≥ from"):
        segment.plan_segment(book, frm=5, to=3)


@pytest.mark.parametrize("total,stages", [
    (1, 1), (2, 2), (3, 3), (4, 3), (10, 3), (11, 4), (13, 4), (14, 5), (30, 5),
])
def test_stage_count_is_half_up_like_js(total, stages):
    # JS: max(1, min(5, total, max(3, Math.round(total / 3))))
    got = max(1, min(5, total, max(3, int(total / 3 + 0.5))))
    assert got == stages
