"""Per-project exclusive lock: fcntl.flock on <root>/.novel-studio.lock.

Reentrant within a thread (nested store calls don't deadlock); blocks other threads/processes.
flock is per open file description, so two fds in one process still exclude each other.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_held = threading.local()


def _depth() -> dict[str, int]:
    d = getattr(_held, "held", None)
    if d is None:
        d = {}
        _held.held = d
    return d


@contextmanager
def project_lock(
    root: str | os.PathLike,
    *,
    timeout: float = 20.0,
) -> Iterator[None]:
    key = str(Path(os.path.abspath(root)))
    held = _depth()
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return

    Path(key).mkdir(parents=True, exist_ok=True)
    lock_file = Path(key) / ".novel-studio.lock"
    fh = open(lock_file, "a+", encoding="utf-8")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"这本书正被另一个会话写入（锁文件 {lock_file}），等它写完再试；"
                        "确认没人在写可删掉该锁文件"
                    )
                time.sleep(0.05)
        # 锁文件保留作锚点(删掉会让两个锁持有者指向不同 inode)；内容是诊断信息，出锁后清空。
        fh.seek(0)
        fh.truncate()
        fh.write(f'{{"pid": {os.getpid()}}}')
        fh.flush()
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def describe_holder(root: str | os.PathLike) -> str:
    lock_file = Path(os.path.abspath(root)) / ".novel-studio.lock"
    try:
        return lock_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
