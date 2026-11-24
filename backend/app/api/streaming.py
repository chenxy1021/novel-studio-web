"""SSE：把一次长生成放到后台线程里跑，边跑边把过程推给前端。

一次生成可能是一到四分钟。同步接口期间前端只能看到一个转圈；这里把
「现在做到哪一步 / 已经写出来的字」实时推过去，作者能看着它长出来。

事件（每行 `data:` 里是一个 JSON 对象）：

- ``{"type":"stage","label":"写正文"}``：阶段切换
- ``{"type":"delta","text":"……"}``：新增的一段正文
- ``{"type":"reason","text":"……"}``：模型思考过程（AI 复检这类要让作者看见思路的生成）
- ``{"type":"done","result":{…}}``：成功，payload 与同步接口完全一致
- ``{"type":"error","code":"LLM_ERROR","message":"…"}``：失败（HTTP 状态已在 code/status 里）

线程里只负责跑活；收尾一定投一个 ``None``，前端不会永远挂着。
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any, Callable

from fastapi.responses import StreamingResponse

from ..domain.errors import DomainError
from ..domain.review import ChapterBlocked, ChapterNotFound, ReviewError
from ..llm import LLMError

HEARTBEAT_SECONDS = 10.0
Emit = Callable[[dict[str, Any]], None]


def error_event(e: BaseException) -> dict[str, Any]:
    """把领域异常映射成前端能识别的错误事件（与同步接口的 detail 同构）。"""
    if isinstance(e, DomainError):
        event: dict[str, Any] = {
            "type": "error", "code": e.code, "message": str(e), "status": e.status_code,
        }
        if e.retryable:
            event["retryable"] = True
        if e.findings:
            event["findings"] = e.findings
        if e.field:
            event["field"] = e.field
        return event
    if isinstance(e, ChapterBlocked):
        return {"type": "error", "code": "CHAPTER_BLOCKED", "message": str(e),
                "status": 409, "findings": e.findings}
    if isinstance(e, ChapterNotFound):
        return {"type": "error", "code": "CHAPTER_NOT_FOUND", "message": str(e), "status": 404}
    if isinstance(e, ReviewError):
        return {"type": "error", "code": "REVIEW_ERROR", "message": str(e), "status": 400}
    if isinstance(e, LLMError):
        return {"type": "error", "code": "LLM_ERROR", "message": str(e),
                "status": 502, "retryable": True}
    if isinstance(e, TimeoutError):
        return {"type": "error", "code": "WRITE_TIMEOUT", "message": str(e),
                "status": 409, "retryable": True}
    if isinstance(e, ValueError):
        return {"type": "error", "code": "BAD_REQUEST", "message": str(e), "status": 400}
    return {"type": "error", "code": "INTERNAL", "message": str(e) or e.__class__.__name__,
            "status": 500}


def sse_response(work: Callable[[Emit], None]) -> StreamingResponse:
    """``work(emit)`` 在后台线程执行；生成器把事件按 SSE 写出。"""
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def emit(event: dict[str, Any]) -> None:
        events.put(event)

    def runner() -> None:
        try:
            work(emit)
        except BaseException as e:  # noqa: BLE001 — 任何失败都要告诉前端
            emit(error_event(e))
        finally:
            events.put(None)

    def generate():
        thread = threading.Thread(target=runner, daemon=True, name="novel-sse")
        thread.start()
        yield ": open\n\n"
        while True:
            try:
                event = events.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                # 模型长时间不吐字时发注释行，代理和浏览器都不会掐断连接。
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
