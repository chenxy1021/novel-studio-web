import os
from pathlib import Path

import pytest

from app import db

BOOKS_ROOT = Path(os.environ.get("DSH_NOVEL_HOME") or Path.home() / "Desktop" / "mine" / "xiaoshuo")
SIGNAL_TOWER = BOOKS_ROOT / "最后一座信号塔"
HUNTING_TOWER = BOOKS_ROOT / "猎场第一百层"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own SQLite file; files are left for pytest to clean up."""
    monkeypatch.setenv("DSH_NOVEL_DB", str(tmp_path / "studio.db"))
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
