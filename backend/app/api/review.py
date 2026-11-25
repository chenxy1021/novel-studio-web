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
    AbandonBody,
    ArchiveBody,
    BatchBody,
    DismissCheckBody,
    ForeshadowBody,
    ForeshadowIdBody,
    ParagraphRewriteBody,
    PayoffBody,
    RejectBody,
    ResolveAiBody,
    RewriteBody,
    SaveChapterBody,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/chapters/{number}/check")
def check_chapter(number: int, dir: str) -> dict:
    path = book_dir(dir)
    try:
        result = review.check_chapter(path, number)
    except Exception as e:  # noqa: BLE001 - mapped to HTTP below
        raise_review(e)
        raise
    review.record_check(path, result)
    return result


@router.post("/check-batch")
def check_batch(body: BatchBody, dir: str) -> dict:
    path = book_dir(dir)
    try:
        result = review.check_batch(path, body.from_chapter, body.to_chapter, verify=body.verify)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise
    # 按批体检和单章体检写同一份缓存：页面刷新后两处看到的是同一批结果。
    for row in result.get("chapters") or []:
        review.record_check(path, row)
    return result


@router.get("/checks")
def list_checks(dir: str) -> dict:
    """各章最近一次确定性体检；stale 表示体检后正文又改过。"""
    return {"rows": review.load_checks(book_dir(dir))}


@router.post("/chapters/{number}/check/dismiss")
def dismiss_check(number: int, body: DismissCheckBody, dir: str) -> dict:
    """这条确定性体检是误报：记下忽略，之后重跑不再计入。"""
    try:
        result = review.dismiss_check(
            book_dir(dir), number, body.code,
            message=body.message, quote=body.quote, line=body.line, offset=body.offset,
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise
    return {"ok": True, "check": result}


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
            findings=[f.model_dump() for f in body.findings] if body.findings else None,
            dismissed=body.dismissed,
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/chapters/{number}/rewrite/stream")
def rewrite_chapter_stream(number: int, body: RewriteBody, dir: str):
    """同 `/rewrite`，流式返回改写中的正文。"""
    path = book_dir(dir)
    findings = [f.model_dump() for f in body.findings] if body.findings else None

    def work(emit: streaming.Emit) -> None:
        result = review.rewrite_chapter(
            path, number,
            note=body.reason, instruction=body.instruction, model=body.model,
            skills=body.skills,
            findings=findings,
            dismissed=body.dismissed,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/chapters/{number}/rewrite-paragraph/stream")
def rewrite_paragraph_stream(number: int, body: ParagraphRewriteBody, dir: str):
    """只重写体检命中的那一段，流式返回；改完验证原句是否消失。"""
    path = book_dir(dir)
    finding = body.finding.model_dump() if body.finding else None

    def work(emit: streaming.Emit) -> None:
        result = review.rewrite_paragraph(
            path, number, body.paragraph,
            instruction=body.instruction, finding=finding, model=body.model,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/chapters/{number}/ai-check")
def ai_check_chapter(number: int, body: RewriteBody, dir: str) -> dict:
    try:
        return review.ai_check_chapter(book_dir(dir), number, model=body.model, force=body.force)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.get("/chapters/{number}/ai-check/current")
def current_ai_check(number: int, dir: str) -> dict:
    """这一章进行中的复检轮次。不调用模型，前端刷新页面后用它把复检结论捞回来。"""
    try:
        payload = review.carried_ai_check(book_dir(dir), number)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise
    return {"carried": bool(payload), "result": payload}


@router.post("/chapters/{number}/ai-check/resolve")
def resolve_ai_finding(number: int, body: ResolveAiBody, dir: str) -> dict:
    """把一轮复检里的一条记成已解决；不重新问模型。"""
    try:
        return review.resolve_ai_finding(
            book_dir(dir), number, body.code, body.message, how=body.how,
        )
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/chapters/{number}/ai-check/stream")
def ai_check_chapter_stream(number: int, body: RewriteBody, dir: str):
    """同 `/ai-check`，额外把模型的思考过程按 reason 事件推给前端。"""
    path = book_dir(dir)

    def work(emit: streaming.Emit) -> None:
        native_reason = False
        sent = 0
        pieces: list[str] = []

        def on_reason(text: str) -> None:
            nonlocal native_reason
            native_reason = True
            emit({"type": "reason", "text": text})

        def on_delta(chunk: str) -> None:
            """模型不吐 reasoning_content 时，把 JSON 前面的审稿思路当思考过程推。"""
            nonlocal sent
            pieces.append(chunk)
            if native_reason:
                return
            text = "".join(pieces)
            cut = text.find("[")
            upto = len(text) if cut < 0 else cut
            if upto > sent:
                emit({"type": "reason", "text": text[sent:upto]})
                sent = upto

        result = review.ai_check_chapter(
            path, number,
            model=body.model,
            force=body.force,
            on_delta=on_delta,
            on_reason=on_reason,
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


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


@router.post("/foreshadow/reopen")
def reopen_foreshadow(body: ForeshadowIdBody, dir: str) -> dict:
    """把自动记收判错的伏笔改回未收：只追加一条 reopen 事件。"""
    try:
        return review.reopen_foreshadow(book_dir(dir), body.id)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


@router.post("/foreshadow/abandon")
def abandon_foreshadow(body: AbandonBody, dir: str) -> dict:
    """明确放弃一条伏笔：不再提醒，也不删账。"""
    try:
        return review.abandon_foreshadow(book_dir(dir), body.id, note=body.note)
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
