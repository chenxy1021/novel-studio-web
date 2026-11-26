"""本系统的数据目录：SQLite、模型设置、最近打开列表。

以前这些都放在 DeepSeek Harness 的 ``~/.dsh/novel-studio/`` 下（旧插件留下的路径）。
现在插件已移除，数据跟着系统走：默认放在仓库根的 ``data/``，不再碰 harness 目录。

``NOVEL_STUDIO_HOME`` 可整体换位置（测试用它隔离）；旧的单项环境变量
（``DSH_NOVEL_DB`` / ``DSH_NOVEL_GATEWAY_FILE`` / ``DSH_NOVEL_RECENT_FILE``）
仍保留，优先级高于 ``NOVEL_STUDIO_HOME``，方便临时指向某个文件。
"""

from __future__ import annotations

import os
from pathlib import Path

# app/core/home.py -> app/core -> app -> backend -> 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]


def studio_home() -> Path:
    """数据目录：``NOVEL_STUDIO_HOME`` 或 ``<仓库>/data``。"""
    raw = (os.environ.get("NOVEL_STUDIO_HOME") or "").strip()
    home = Path(raw).expanduser() if raw else REPO_ROOT / "data"
    home.mkdir(parents=True, exist_ok=True)
    return home
