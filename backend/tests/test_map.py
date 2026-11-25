"""地图提示词与 SVG 清洗：全部离线，不调模型。"""

from __future__ import annotations

import pytest

from app.domain import map_gen


def test_prompt_contains_worldview_and_locations() -> None:
    project = {"title": "雾港纪事", "genre": "悬疑", "worldText": "雾港分东西两岸，中间是渡口。"}
    bible = {
        "locations": [
            {"name": "东岸", "mapScope": "雾港", "geo": "渡口以东"},
            {"name": "西岸", "mapScope": "雾港", "mapBearing": "西"},
        ],
        "society": {"customs": "过江要留一盏灯"},
        "factions": [{"name": "船行会", "nature": "把控渡口"}],
    }
    messages = map_gen._messages(project, bible)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "只输出一个完整的 <svg>" in system
    assert "雾港分东西两岸" in user
    assert "东岸" in user and "西岸" in user
    assert "船行会" in user
    assert "过江要留一盏灯" in user


def test_extract_svg_strips_script_and_handlers() -> None:
    raw = """```svg
<svg viewBox="0 0 1000 720" xmlns="http://www.w3.org/2000/svg">
  <script>alert(1)</script>
  <rect width="10" height="10" onclick="alert(1)" />
  <text>渡口</text>
</svg>
```"""
    svg = map_gen._extract_svg(raw)
    assert svg.startswith("<svg")
    assert "渡口" in svg
    assert "<script" not in svg
    assert "onclick" not in svg


def test_extract_svg_rejects_non_svg() -> None:
    with pytest.raises(ValueError):
        map_gen._extract_svg("抱歉，我画不出来。")


def test_extract_svg_adds_missing_namespace() -> None:
    svg = map_gen._extract_svg('<svg viewBox="0 0 10 10"><text>渡口</text></svg>')
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_extract_svg_drops_percentage_root_size() -> None:
    """根标签的 width="100%" / height="auto" 在 <img> 里无效，留 viewBox 定比例。"""
    svg = map_gen._extract_svg(
        '<svg viewBox="0 0 1000 720" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">'
        "<text>渡口</text></svg>"
    )
    head = svg[: svg.find(">") + 1]
    assert "height=" not in head
    assert "width=" not in head
    assert 'viewBox="0 0 1000 720"' in head


def test_draw_svg_retries_once_without_svg(monkeypatch) -> None:
    """模型先说了段废话没给图：再要一次，并明说不要分析。"""
    calls: list[list[dict[str, str]]] = []

    def fake_chat(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {"text": "抱歉，我画不出来。", "model": "m", "usage": {}}
        return {
            "text": '<svg viewBox="0 0 10 10"><text>渡口</text></svg>',
            "model": "m",
            "usage": {},
        }

    monkeypatch.setattr(map_gen, "chat", fake_chat)
    svg, out = map_gen.draw_svg([{"role": "user", "content": "画图"}])
    assert svg.startswith("<svg") and "渡口" in svg
    assert len(calls) == 2
    assert "不要分析" in calls[1][-1]["content"]
    assert out["model"] == "m"


def test_draw_svg_raises_when_retry_also_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        map_gen, "chat", lambda *a, **k: {"text": "还是画不出来。", "model": "m", "usage": {}}
    )
    with pytest.raises(ValueError):
        map_gen.draw_svg([{"role": "user", "content": "画图"}])


def test_load_map_defaults_when_missing(tmp_path) -> None:
    assert map_gen.load_map(tmp_path) == {"svg": "", "at": "", "model": ""}
