"""按写作阶段选思考强度。

同一个网关模型，开书蓝图值得多想，章记忆不值得。这里集中给默认档位：
- blueprint / concepts / settings：high（一次定全局，错一步后面全歪）
- outline / foreshadow / prose / rewrite：medium
- memory：none（从正文提炼，不需要推理链）
- check：none（复检的「思考过程」由提示词要求先写「审稿思路」，原生推理会吃掉
  输出额度——那两处调用明确保持 none，不走这里的 high）

``NOVEL_STUDIO_REASONING`` 可传 JSON 覆盖单项，例如
``{"prose": "high", "outline": "low"}``；只接受 none/low/medium/high。
"""

from __future__ import annotations

import json
import os

LEVELS = ("none", "low", "medium", "high")

DEFAULTS: dict[str, str] = {
    "blueprint": "high",
    "concepts": "high",
    "settings": "high",
    "outline": "medium",
    "foreshadow": "medium",
    "prose": "medium",
    "rewrite": "medium",
    "memory": "none",
    "check": "none",
}


def _overrides() -> dict[str, str]:
    raw = (os.environ.get("NOVEL_STUDIO_REASONING") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if str(v) in LEVELS
    }


def reasoning_for(stage: str) -> str:
    """这个阶段该用哪档推理；未知阶段退回 low。"""
    key = str(stage or "").strip()
    return _overrides().get(key) or DEFAULTS.get(key, "low")
