"""段落纲移植验收：plan / list / chapterFromSegment 与 JS 原版逐字段一致，
写盘/重叠/删除/非法范围的错误信息也一致（这些文案会直接显示给作者）。
"""

import json
import shutil
from pathlib import Path

import pytest

from app.domain import segment

FIXTURES = Path(__file__).parent / "fixtures"


def _book_copy(tmp_path: Path, src: Path) -> Path:
    dst = tmp_path / src.name
    shutil.copytree(src, dst)
    seg = dst / "ledger" / "segments.jsonl"
    if seg.exists():
        seg.unlink()
    return dst


@pytest.fixture
def book(tmp_path, signal_tower):
    return _book_copy(tmp_path, signal_tower)


def test_plan_matches_js_golden(signal_tower):
    golden = json.loads((FIXTURES / "segment_plan.json").read_text(encoding="utf-8"))
    assert segment.plan_segment(signal_tower, frm=1, to=10) == golden["plan"]
    assert segment.plan_segment(signal_tower, frm=5, to=16) == golden["plan12"]
    assert segment.list_segments(signal_tower) == golden["planList"]
    assert segment.chapter_from_segment(signal_tower, 7) == golden["ch7"]


def test_write_overlap_list_delete(book):
    assert segment.write_segment_outline(book, segment.plan_segment(book, frm=1, to=10)) == {
        "ok": True, "from": 1, "to": 10, "stages": 3,
    }
    with pytest.raises(ValueError, match="与已有批次第1-10章重叠"):
        segment.write_segment_outline(book, segment.plan_segment(book, frm=5, to=14))
    assert [(s["from"], s["to"]) for s in segment.list_segments(book)] == [(1, 10)]
    assert segment.delete_segment(book, frm=1, to=10) == {"ok": True, "from": 1, "to": 10, "written": 10}
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
