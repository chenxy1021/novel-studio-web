import pytest

from app import db


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
