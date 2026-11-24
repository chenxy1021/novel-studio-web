"""进程内写作并发表：同一本书同时只允许一个 runId 在写。

表结构：``{dir: {runId, chapter, stage, startedAt}}``。只存在内存里，重启即清空，
不做持久化；旧运行由前端快照提示检查。

语义（design §9.2）：
- 同 dir、不同 runId、15 分钟内 → ``WriteBusy``（HTTP 409 ``WRITE_BUSY``，retryable）。
- 同 runId 重试放行（刷新 chapter/stage/startedAt）。
- 不同 dir 互不影响；超过 TTL 视为空闲。

结构对单章改写可复用：后续 ``REWRITE_BUSY`` 只要换一个 key（如 ``dir#rewrite#n``）
或换一张表即可，无需改 acquire/release 形态。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from .errors import WriteBusy

TTL_SECONDS = 15 * 60

_ACTIVE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _key(root: str | os.PathLike) -> str:
    return os.path.realpath(os.path.abspath(str(root)))


def _expired(entry: dict[str, Any], now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    try:
        started = float(entry.get("startedAt") or 0)
    except (TypeError, ValueError):
        return True
    return now - started >= TTL_SECONDS


def current(root: str | os.PathLike) -> dict[str, Any] | None:
    """Return the active run for ``root`` (or ``None``). Expired entries are dropped."""
    key = _key(root)
    with _LOCK:
        entry = _ACTIVE.get(key)
        if not entry:
            return None
        if _expired(entry):
            _ACTIVE.pop(key, None)
            return None
        return dict(entry)


def is_busy(root: str | os.PathLike, run_id: str | None) -> bool:
    """True when another runId holds this dir; the same runId is never busy."""
    entry = current(root)
    if not entry:
        return False
    return bool(run_id) and entry.get("runId") != run_id


def acquire(root: str | os.PathLike, run_id: str, chapter: int, stage: str) -> dict[str, Any]:
    """Claim the dir for ``run_id`` or raise ``WriteBusy``. Same runId is allowed."""
    key = _key(root)
    now = time.monotonic()
    with _LOCK:
        entry = _ACTIVE.get(key)
        if entry and not _expired(entry, now) and entry.get("runId") != run_id:
            busy_chapter = entry.get("chapter") or "?"
            busy_stage = entry.get("stage") or "writing"
            raise WriteBusy(f"另一个窗口正在写第{busy_chapter}章（{busy_stage}），等它写完再试")
        info = {
            "runId": str(run_id),
            "chapter": int(chapter),
            "stage": str(stage),
            "startedAt": now,
        }
        _ACTIVE[key] = info
        return dict(info)


def release(root: str | os.PathLike, run_id: str | None) -> None:
    """Release only when ``run_id`` still owns the dir; stale releases are ignored."""
    if not run_id:
        return
    key = _key(root)
    with _LOCK:
        entry = _ACTIVE.get(key)
        if entry and entry.get("runId") == run_id:
            _ACTIVE.pop(key, None)


def reset() -> None:
    """Clear the whole table (tests / process restart)."""
    with _LOCK:
        _ACTIVE.clear()
