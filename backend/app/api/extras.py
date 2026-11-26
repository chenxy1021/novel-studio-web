"""结构视图与全书级动作：组织架构 / 章节图谱 / 滚动规划 / 审美复检 / 回灌 / 导出。

这些接口都不属于「写正文」的主流程，放在单独的路由里，避免 books/studio/review
三个文件越滚越大。写 bible 的动作仍走 ``project_lock``；会调模型的动作用
``runs.acquire`` 占住这本书，避免和另一个窗口的写作撞车。
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from ..domain import (
    aesthetic,
    chapter_graph,
    export,
    hierarchy,
    related,
    rolling,
    runs,
    sync,
)
from .deps import book_dir
from .errors import raise_generation, raise_review
from .schemas import AestheticBody, CompassBody, HierarchyBody, RollingBody, SyncBody

router = APIRouter(prefix="/projects", tags=["projects"])


def _run_id(raw: str) -> str:
    return raw or f"adhoc-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# 组织架构 + 职业等级
# --------------------------------------------------------------------------- #


@router.get("/hierarchy")
def get_hierarchy(dir: str) -> dict:
    return hierarchy.hierarchy_view(book_dir(dir))


@router.post("/hierarchy/generate")
def generate_hierarchy(body: HierarchyBody, dir: str) -> dict:
    path = book_dir(dir)
    run_id = _run_id(body.runId)
    try:
        runs.acquire(path, run_id, 0, "设定")
        try:
            return hierarchy.generate_hierarchy(path, model=body.model or None)
        finally:
            runs.release(path, run_id)
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
        raise


# --------------------------------------------------------------------------- #
# 章节关系图谱 + 相关章节
# --------------------------------------------------------------------------- #


@router.get("/chapter-graph")
def get_chapter_graph(dir: str) -> dict:
    return chapter_graph.build_chapter_graph(book_dir(dir))


@router.get("/related-chapters")
def get_related_chapters(dir: str, chapter: int | None = None, limit: int = 8) -> dict:
    path = book_dir(dir)
    rows = related.related_chapters(path, chapter, limit=limit)
    return {
        "chapter": chapter or 0,
        "items": rows,
        "text": related.related_block(path, chapter, limit=min(5, max(1, limit))),
    }


# --------------------------------------------------------------------------- #
# 滚动规划
# --------------------------------------------------------------------------- #


@router.get("/rolling")
def get_rolling(dir: str) -> dict:
    return rolling.rolling_status(book_dir(dir))


@router.post("/rolling/compass")
def save_compass(body: CompassBody, dir: str) -> dict:
    try:
        return rolling.set_compass(book_dir(dir), body.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e


@router.post("/rolling/plan")
def plan_rolling(body: RollingBody, dir: str) -> dict:
    path = book_dir(dir)
    run_id = _run_id(body.runId)
    try:
        runs.acquire(path, run_id, 0, "滚动规划")
        try:
            return rolling.rolling_plan(
                path, chapters=body.chapters, model=body.model or None, force=body.force,
            )
        finally:
            runs.release(path, run_id)
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
        raise


# --------------------------------------------------------------------------- #
# 审美五项
# --------------------------------------------------------------------------- #


@router.get("/aesthetic")
def get_aesthetic(dir: str, chapter: int) -> dict:
    row = aesthetic.rating(book_dir(dir), chapter)
    return {"chapter": chapter, "rating": row, "dimensions": [
        {"key": k, "label": label, "hint": hint} for k, label, hint in aesthetic.DIMENSIONS
    ]}


@router.post("/chapters/{number}/aesthetic")
def run_aesthetic(number: int, body: AestheticBody, dir: str) -> dict:
    path = book_dir(dir)
    try:
        return aesthetic.aesthetic_check(path, number, text=body.text, model=body.model or None)
    except Exception as e:  # noqa: BLE001
        raise_review(e)
        raise


# --------------------------------------------------------------------------- #
# 手改回灌
# --------------------------------------------------------------------------- #


@router.get("/sync")
def scan_sync(dir: str) -> dict:
    return sync.scan_sync(book_dir(dir))


@router.post("/sync/apply")
def apply_sync(body: SyncBody, dir: str) -> dict:
    path = book_dir(dir)
    run_id = _run_id(body.runId)
    try:
        runs.acquire(path, run_id, 0, "回灌")
        try:
            return sync.apply_sync(
                path, body.numbers,
                regenerate_memory=body.regenerateMemory, model=body.model or None,
            )
        finally:
            runs.release(path, run_id)
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
        raise


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #


@router.post("/export")
def make_export(dir: str) -> dict:
    try:
        return export.export_txt(book_dir(dir))
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e


@router.get("/export/txt")
def download_export(dir: str) -> Response:
    try:
        built = export.build_export(book_dir(dir))
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    name = quote(built["filename"])
    return Response(
        content=built["text"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )
