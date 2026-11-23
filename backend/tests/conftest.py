import os
from pathlib import Path

import pytest

BOOKS_ROOT = Path(os.environ.get("DSH_NOVEL_HOME") or Path.home() / "Desktop" / "mine" / "xiaoshuo")
SIGNAL_TOWER = BOOKS_ROOT / "最后一座信号塔"
HUNTING_TOWER = BOOKS_ROOT / "猎场第一百层"


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
