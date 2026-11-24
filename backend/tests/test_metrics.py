"""metrics 移植验收：与 JS 原版逐字段相等。

golden 数据由 novel-studio/lib/metrics.js 原版直接跑出来（scripts/gen_metrics_golden.mjs），
任何移植改动导致数字漂移，这里会红。
"""

import json
from pathlib import Path

import pytest

from app.domain import metrics

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLES = json.loads((FIXTURES / "metrics_samples.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((FIXTURES / "metrics_golden.json").read_text(encoding="utf-8"))


def _golden_shape(tells):
    """golden 来自 JS 版，只有 line/text；定位字段由切片 4 新增，不参与逐字对齐。"""
    return [
        {
            **t,
            "samples": [{k: s[k] for k in ("line", "text")} for s in t.get("samples", [])],
        }
        for t in tells
    ]


@pytest.mark.parametrize("i", range(len(SAMPLES)))
def test_matches_js_golden(i):
    text = SAMPLES[i]
    m = metrics.text_metrics(text)
    tells = metrics.detect_ai_tells(text)
    assert m == GOLDEN[i]["metrics"], f"samples[{i}] textMetrics"
    assert _golden_shape(tells) == GOLDEN[i]["tells"], f"samples[{i}] detectAiTells"
    for t in tells:
        for s in t.get("samples", []):
            assert isinstance(s["paragraph"], int) and s["paragraph"] >= 1
            assert isinstance(s["offset"], int) and s["offset"] >= 0
    assert metrics.count_chars(text) == GOLDEN[i]["chars"], f"samples[{i}] countChars"
    assert metrics.estimate_tokens(text) == GOLDEN[i]["tokens"], f"samples[{i}] estimateTokens"
    assert metrics.verdict(m, tells) == GOLDEN[i]["verdict"], f"samples[{i}] verdict"
    assert metrics.check_chapter_end_hook(text) == GOLDEN[i]["hook"], f"samples[{i}] hook"


def test_round_half_up_like_tofixed():
    # V8 的 toFixed 是 half-up；Python round() 是 half-even，必须不一样
    assert metrics._round(13.25, 1) == 13.3
    assert metrics._round(16.25, 1) == 16.3
    assert metrics._round(0.125, 2) == 0.13
    assert metrics._round(13.35, 1) == 13.3


def test_verdict_thresholds_are_the_single_source():
    # 域A口径：差 = high>=2 或 density>2.5；中 = density>2 或 high>=1
    ok = {"chars": 1000, "paragraphBurstiness": 0.9, "sentenceBurstiness": 0.9}
    one_high = [{"severity": "high", "count": 1}]
    two_high = [{"severity": "high", "count": 2}]
    assert metrics.verdict(ok, [])["level"] == "良"
    assert metrics.verdict(ok, one_high)["level"] == "中"
    assert metrics.verdict(ok, two_high)["level"] == "差"
    assert metrics.verdict(ok, [{"severity": "mid", "count": 3}])["level"] == "差"
    # 1 个 mid / 1000 字 = 1.0 密度，不到 >2；2 个正好 2.0 也还是「良」（严格大于）
    assert metrics.verdict(ok, [{"severity": "mid", "count": 2}])["level"] == "良"
    assert metrics.verdict({"chars": 500, "paragraphBurstiness": 0.9, "sentenceBurstiness": 0.9},
                           [{"severity": "mid", "count": 2}])["level"] == "差"
