"""记忆页：整包记忆 / 关键词回查 / 章、卷、批量记忆生成。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..domain import memory as memory_mod
from ..domain import memory_gen
from ..store import chapter as chapters
from ..store import load_project
from .deps import book_dir
from .errors import bad_request, raise_memory
from .schemas import MemoryBatchBody, MemoryGenBody

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/memory")
def get_memory(dir: str) -> dict:
    """记忆页整包数据：覆盖度、章/卷记忆、时间线、关系、人物状态；只读，不调模型。"""
    return memory_gen.memory_overview(book_dir(dir))


@router.get("/memory/recall")
def recall_memory(
    dir: str,
    q: str = "",
    frm: int | None = Query(default=None, alias="from"),
    to: int | None = None,
) -> dict:
    """关键词回查：正文切片 + 记忆事件/摘要 + 伏笔/细纲命中，带章号出处。"""
    found = memory_mod.recall_memory(book_dir(dir), query=q, frm=frm, to=to)
    hits = [
        {
            "chapter": int(h.get("chapter") or 0),
            "title": str(h.get("title") or ""),
            "text": str(h.get("quote") or h.get("summary") or ""),
            "score": int(h.get("score") or 0),
        }
        for h in (found.get("hits") or [])
    ]
    return {"hits": hits}


@router.post("/memory/chapter/{number}/generate")
def generate_memory_chapter(number: int, body: MemoryGenBody, dir: str) -> dict:
    """从第 n 章正文提炼章记忆 + 时间线。已有记忆且 force=false 时跳过。"""
    try:
        result = memory_gen.generate_chapter_memory(
            book_dir(dir), number, model=body.model, force=body.force,
        )
    except Exception as e:  # noqa: BLE001 - mapped below
        raise_memory(e)
        raise
    return {"ok": True, **result}


@router.post("/memory/volume/{idx}/generate")
def generate_memory_volume(idx: int, body: MemoryGenBody, dir: str) -> dict:
    """按卷生成卷摘要 + 六维度；已有同范围卷记忆且 force=false 时跳过。"""
    try:
        result = memory_gen.generate_volume_memory(
            book_dir(dir), idx, model=body.model, force=body.force,
        )
    except Exception as e:  # noqa: BLE001
        raise_memory(e)
        raise
    return {"ok": True, **result}


@router.post("/memory/generate")
def generate_memory_batch(body: MemoryBatchBody, dir: str) -> dict:
    """批量补章记忆；from/to 缺省时从第一个缺记忆的章补到 currentChapter。"""
    path = book_dir(dir)
    try:
        frm, to = body.from_chapter, body.to_chapter
        if frm is None or to is None:
            project = load_project(path) or {}
            index = chapters.read_index(path)
            written = sorted({int(c["number"]) for c in index if int(c.get("chars") or 0) > 0})
            if not written:
                raise bad_request("还没有可生成记忆的正文")
            by_chapter = memory_mod.load_memory_rows(path)["byChapter"]
            missing = [n for n in written if not str((by_chapter.get(n) or {}).get("summary") or "").strip()]
            if frm is None:
                frm = missing[0] if missing else written[0]
            if to is None:
                to = max(int(project.get("currentChapter") or 0), written[-1])
        result = memory_gen.generate_memory_batch(
            path, frm, to, model=body.model, force=body.force,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise_memory(e)
        raise
    return {"ok": True, **result}
