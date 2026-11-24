"""Domain exception -> HTTP body mapping shared by the project routers.

All routers return the same ``{code, message, retryable?, findings?, field?}``
detail shape so the frontend can handle errors uniformly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..domain import review
from ..domain.errors import DomainError
from ..llm import LLMError


def raise_domain(e: DomainError) -> None:
    """统一错误体：{code, message, retryable?, findings?, field?}。"""
    detail: dict[str, Any] = {"code": e.code, "message": str(e)}
    if e.retryable:
        detail["retryable"] = True
    if e.findings:
        detail["findings"] = e.findings
    if e.field:
        detail["field"] = e.field
    raise HTTPException(status_code=e.status_code, detail=detail) from e


def raise_generation(e: Exception) -> None:
    """写作 / 细纲 / 正文：领域错误、模型 502、忙 409、参数 400。"""
    if isinstance(e, DomainError):
        raise_domain(e)
    if isinstance(e, LLMError):
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    if isinstance(e, TimeoutError):
        raise HTTPException(status_code=409, detail={
            "code": "WRITE_TIMEOUT", "message": str(e), "retryable": True,
        }) from e
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    raise e


def raise_memory(e: Exception) -> None:
    """记忆生成错误映射：模型问题 502，忙/超时 409，其余按领域错误/400。"""
    if isinstance(e, LLMError):
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    if isinstance(e, TimeoutError):
        raise HTTPException(status_code=409, detail={
            "code": "WRITE_TIMEOUT", "message": str(e), "retryable": True,
        }) from e
    if isinstance(e, DomainError):
        raise_domain(e)
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    raise e


def raise_review(e: Exception) -> None:
    if isinstance(e, review.ChapterBlocked):
        raise HTTPException(status_code=409, detail={"message": str(e), "findings": e.findings}) from e
    if isinstance(e, review.ChapterNotFound):
        raise HTTPException(status_code=404, detail=str(e)) from e
    if isinstance(e, review.ReviewError):
        raise HTTPException(status_code=400, detail=str(e)) from e
    if isinstance(e, LLMError):
        raise HTTPException(status_code=502, detail=str(e)) from e
    if isinstance(e, TimeoutError):
        raise HTTPException(status_code=409, detail=str(e)) from e
    raise e


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": message})


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
