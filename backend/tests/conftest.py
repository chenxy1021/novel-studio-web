import os
from pathlib import Path

import pytest

from app import db

BOOKS_ROOT = Path(os.environ.get("DSH_NOVEL_HOME") or Path.home() / "Desktop" / "mine" / "xiaoshuo")
# 真实书稿目录在 import 时定下来：conftest 会改 DSH_NOVEL_HOME，固定住才能找到样例书。

SIGNAL_TOWER = BOOKS_ROOT / "最后一座信号塔"
HUNTING_TOWER = BOOKS_ROOT / "猎场第一百层"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own data dir; files are left for pytest to clean up."""
    # 数据目录（SQLite / gateway.json / recent.json）整体隔离，测试不碰仓库里的 data/。
    monkeypatch.setenv("NOVEL_STUDIO_HOME", str(tmp_path / "home"))
    # 书稿目录也要隔离，否则建书测试会往真实书架里长「连续测试*」目录。
    # projects_root() 每次调用都读环境变量，所以这里改环境变量就够，不用 patch 常量。
    monkeypatch.setenv("DSH_NOVEL_HOME", str(tmp_path / "books"))
    # 正文落盘后的记忆回写会多调一次模型；测试默认关掉，需要覆盖的测试自己打开。
    monkeypatch.setenv("DSH_NOVEL_AUTO_MEMORY", "0")
    db.reset()
    yield


def _book_or_skip(path: Path):
    if not (path / "project.json").is_file():
        pytest.skip(f"真实书稿不在 {path}")
    return path


@pytest.fixture
def signal_tower() -> Path:
    return _book_or_skip(SIGNAL_TOWER)


@pytest.fixture
def hunting_tower() -> Path:
    return _book_or_skip(HUNTING_TOWER)
