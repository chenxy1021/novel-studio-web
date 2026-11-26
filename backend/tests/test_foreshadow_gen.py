"""伏笔生成去重：同一条线换个说法不能重复入库。"""

from __future__ import annotations

import json

from app.domain import foreshadow_gen


def test_same_line_matches_rephrased_seed() -> None:
    old = foreshadow_gen._slot("后窗插销锈死", "detail", 5, 12)
    # 同一件事换个说法：名字不同、埋收章一样。
    assert foreshadow_gen._same_line(old, foreshadow_gen._slot("后窗插销被人焊过", "detail", 5, 12))
    # 层级不同就不是同一条线。
    assert not foreshadow_gen._same_line(old, foreshadow_gen._slot("后窗插销被人焊过", "main", 5, 12))
    # 埋收章差太远，是两条线。
    assert not foreshadow_gen._same_line(old, foreshadow_gen._slot("后窗插销锈死", "detail", 5, 30))
    # 名字几乎不重合，不并。
    assert not foreshadow_gen._same_line(old, foreshadow_gen._slot("账本缺页", "detail", 5, 12))


def test_generate_skips_rephrased_seed(tmp_path, monkeypatch) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({
            "title": "雾港",
            "worldText": "雾港分东西两岸。",
            "outlineText": "卷一：渡口。卷二：账本。",
            "targetChapters": 60,
        }),
        encoding="utf-8",
    )
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / "foreshadow.jsonl").write_text(
        json.dumps({
            "id": "fs-old", "name": "后窗插销锈死", "kind": "detail",
            "plantedChapter": 5, "dueChapter": 12, "status": "open",
        }) + "\n",
        encoding="utf-8",
    )
    line = "后窗插销被人焊过|细节|墙角|5|夜里查窗|12|老秦|知道有人动过窗|窗框有水|当作没看见"
    monkeypatch.setattr(
        foreshadow_gen, "chat",
        lambda *a, **k: {"text": line, "model": "m", "usage": {}},
    )
    res = foreshadow_gen.generate_foreshadows(tmp_path)
    assert res["count"] == 0
    assert res["skipped"] >= 1
    rows = (tmp_path / "ledger" / "foreshadow.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1  # 只有原来那条，没有把同一条线再记一遍
