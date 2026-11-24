"""审阅写回环：体检 / 存档 / 驳回 / 保存 / 改写 / AI 检查 / 伏笔 / 废稿。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..domain import review
from ..store import load_project, project_lock
from . import streaming
from .deps import book_dir
from .errors import bad_request, raise_review
from .schemas import (
    ArchiveBody,
    BatchBody,
    ForeshadowBody,
    PayoffBody,
    RejectBody,
    RewriteBody,
    SaveChapterBody,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/chapters/{number}/check")
def check_chapter(number: int, dir: str) -> dict:
    try:
        return review.check_chapter(book_dir(dir), number)
    except Exception as e:  # noqa: BLE001 - mapped to HTTP below
        raise_review(e)
        raise


@router.post("/check-batch")
def check_batch(body: BatchBody, dir: str) -> dict:
    try:
        return review.check_batch(book_dir(dir), body.from_chapter, body.to_chapter)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/chapters/{number}/archive")
def archive_chapter(number: int, body: ArchiveBody, dir: str) -> dict:
    try:
        return review.archive_chapter(book_dir(dir), number, force=body.force)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/archive-batch")
def archive_batch(body: dict[str, Any], dir: str) -> dict:
    """批量存档：逐章复用 archive_chapter；单章失败不影响其他章，整批 200。"""
    path = book_dir(dir)
    project = load_project(path) or {}

    raw = body.get("numbers")
    if not isinstance(raw, list) or not raw:
        raise bad_request("numbers 必须是非空整数数组")
    numbers: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("numbers 必须是非空整数数组")
        if value not in numbers:
            numbers.append(value)

    force = body.get("force", False)
    if not isinstance(force, bool):
        raise bad_request("force 必须是布尔值")

    target = int(project.get("targetChapters") or 0)
    for number in numbers:
        if number < 1 or (target and number > target):
            raise bad_request(f"章号超出范围：{number}")

    results: list[dict[str, Any]] = []
    with project_lock(path):
        for number in sorted(numbers):
            try:
                res = review.archive_chapter(path, number, force=force)
                results.append({
                    "number": number,
                    "ok": True,
                    "approved": int(res.get("approved") or number),
                })
            except review.ChapterBlocked as e:
                results.append({
                    "number": number, "ok": False, "error": str(e),
                    "code": "CHAPTER_BLOCKED", "findings": e.findings,
                })
            except review.ChapterNotFound as e:
                results.append({
                    "number": number, "ok": False, "error": str(e),
                    "code": "CHAPTER_NOT_FOUND", "findings": [],
                })
            except review.ChapterConflict:
                # 已存档：幂等，算成功但标记 skipped
                results.append({
                    "number": number, "ok": True, "approved": number, "skipped": True,
                })
            except Exception as e:  # noqa: BLE001 - 单章失败不影响整批
                results.append({
                    "number": number, "ok": False, "error": str(e),
                    "code": str(getattr(e, "code", "ERROR")),
                })

    approved_count = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
    failed_count = sum(1 for r in results if not r.get("ok"))
    return {
        "ok": True,
        "results": results,
        "approvedCount": approved_count,
        "failedCount": failed_count,
    }


@router.post("/chapters/{number}/reject")
def reject_chapter(number: int, body: RejectBody, dir: str) -> dict:
    try:
        return review.reject_chapter(book_dir(dir), number, reason=body.reason)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.put("/chapters/{number}")
def save_chapter(number: int, body: SaveChapterBody, dir: str) -> dict:
    try:
        return review.save_chapter_text(
            book_dir(dir), number, body.text, title=body.title, unapprove=body.unapprove,
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/chapters/{number}/rewrite")
def rewrite_chapter(number: int, body: RewriteBody, dir: str) -> dict:
    try:
        return review.rewrite_chapter(
            book_dir(dir), number,
            note=body.reason, instruction=body.instruction, model=body.model,
            skills=body.skills,
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/chapters/{number}/rewrite/stream")
def rewrite_chapter_stream(number: int, body: RewriteBody, dir: str):
    """同 `/rewrite`，流式返回改写中的正文。"""
    path = book_dir(dir)

    def work(emit: streaming.Emit) -> None:
        result = review.rewrite_chapter(
            path, number,
            note=body.reason, instruction=body.instruction, model=body.model,
            skills=body.skills,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/chapters/{number}/ai-check")
def ai_check_chapter(number: int, body: RewriteBody, dir: str) -> dict:
    try:
        return review.ai_check_chapter(book_dir(dir), number, model=body.model)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/foreshadow")
def add_foreshadow(body: ForeshadowBody, dir: str) -> dict:
    try:
        row = review.add_foreshadow(
            book_dir(dir),
            name=body.name,
            kind=body.kind,
            planted_chapter=body.plantedChapter,
            due_chapter=body.dueChapter,
            reveal_who=body.revealWho,
            hint=body.hint,
        )
        return {"ok": True, "row": row}
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/foreshadow/payoff")
def payoff_foreshadow(body: PayoffBody, dir: str) -> dict:
    try:
        return review.payoff_foreshadow(book_dir(dir), body.id, body.chapter)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.get("/discarded")
def list_discarded(dir: str) -> dict:
    path = book_dir(dir)
    return {"dir": str(path), "rows": review.list_discarded(path)}


@router.get("/discarded/read")
def read_discarded(dir: str, draftFile: str) -> dict:
    try:
        return review.read_discarded(book_dir(dir), draftFile)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/discarded/restore")
def restore_discarded(body: dict, dir: str) -> dict:
    try:
        return review.restore_discarded(
            book_dir(dir),
            str(body.get("draftFile") or ""),
            int(body.get("number") or 0),
            str(body.get("title") or ""),
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/discarded/purge")
def purge_discarded(body: dict, dir: str) -> dict:
    try:
        return review.purge_discarded(book_dir(dir), str(body.get("draftFile") or ""))
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise
