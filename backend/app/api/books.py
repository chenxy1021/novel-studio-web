"""书架：书列表 / 平台 / 建书、开书、删书 / 总览 / 章节与设定读取。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core.paths import books_root, book_summary, delete_book, list_books, recent_books
from ..domain import create, review
from ..domain.memory import effective_relations
from ..store import chapter as chapters
from ..store import load_bible, load_project
from ..store.jsonl import fold_by_key, fold_foreshadow, fold_outline, fold_segments, fold_timeline, read_jsonl
from ..store.paths import LEDGER, LAYOUT, LEDGER_KEYS, project_path
from .deps import book_dir
from .schemas import (
    BookOverview,
    ChapterMeta,
    CreateBookBody,
    DeleteBookBody,
    OpenBook,
)

router = APIRouter(prefix="/projects", tags=["projects"])

_FOLDS = {
    "foreshadow": fold_foreshadow,
    "segments": fold_segments,
    "outline": fold_outline,
    "timeline": fold_timeline,
    "dismissed": lambda rows: fold_by_key(rows, "key"),
}


@router.get("")
def get_projects() -> dict:
    return {"root": str(books_root()), "books": list_books(), "recent": recent_books()}


@router.get("/platforms")
def get_platforms() -> dict:
    return {"platforms": create.list_platforms()}


@router.post("/create")
def create_project(body: CreateBookBody) -> dict:
    try:
        book = create.create_book(
            title=body.title,
            genre=body.genre,
            platform=body.platform,
            target_chapters=body.targetChapters,
            words_per_chapter=body.wordsPerChapter,
            logline=body.logline,
            synopsis=body.synopsis,
            theme=body.theme,
            tone=body.tone,
            concepts=body.concepts,
            selected_concept_id=body.selectedConceptId,
            nuewen=body.nuewen,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True, "book": book}


@router.post("/open")
def open_project(body: OpenBook) -> dict:
    return book_summary(book_dir(body.dir))


@router.post("/delete")
def delete_project(body: DeleteBookBody) -> dict:
    try:
        result = delete_book(body.dir, expect_title=body.confirm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True, "deleted": result["dir"], "snapshot": result["snapshot"]}


@router.get("/overview")
def project_overview(dir: str) -> BookOverview:
    path = book_dir(dir)
    project = load_project(path) or {}
    index = chapters.read_index(path)
    written = chapters.written_through(path)
    # gate 是派生值：已写到的章 + 1。project.json 里的旧值可能落后（补存档、回退），
    # 对外一律以章节索引为准，前端所有「下一章」都读这一个数。
    gate = dict(project.get("gate") or {})
    gate["chapter"] = written + 1
    fs_rows = read_jsonl(project_path(path, LEDGER["foreshadow"]))
    return BookOverview(
        dir=str(path),
        title=project.get("title") or path.name,
        genre=project.get("genre") or "",
        platform=project.get("platform") or "",
        logline=project.get("logline") or "",
        synopsis=project.get("synopsis") or "",
        theme=project.get("theme") or "",
        tone=project.get("tone") or "",
        targetChapters=int(project.get("targetChapters") or 0),
        currentChapter=written,
        writtenThrough=written,
        nextChapter=written + 1,
        wordsPerChapter=int(project.get("wordsPerChapter") or 0),
        minChars=review.chapter_min_chars(project),
        segmentSize=max(3, min(30, int(project.get("segmentSize") or 10))),
        updatedAt=str(project.get("updatedAt") or ""),
        gate=gate,
        gates=project.get("gates") or {},
        spine=str(project.get("spine") or project.get("logline") or ""),
        outlineText=str(project.get("outlineText") or ""),
        worldText=str(project.get("worldText") or ""),
        nuewen=bool(project.get("nuewen")),
        outlineAt=str(project.get("outlineAt") or ""),
        settingsAt=str(project.get("settingsAt") or ""),
        foreshadowAt=str(project.get("foreshadowAt") or ""),
        chapters=[
            ChapterMeta(
                number=int(c["number"]),
                title=c.get("title") or "",
                chars=int(c.get("chars") or 0),
                approved=bool(c.get("approved")),
                chapterVerdict=c.get("chapterVerdict") or "pass",
                endHook=c.get("endHook") if isinstance(c.get("endHook"), dict) else None,
            )
            for c in index
        ],
        openForeshadow=sum(1 for f in fold_foreshadow(fs_rows) if f.get("status") == "open"),
        pending=[int(c["number"]) for c in index if not c.get("approved")],
    )


@router.get("/chapters")
def list_chapters(dir: str) -> dict:
    path = book_dir(dir)
    rows = chapters.read_index(path)
    return {"dir": str(path), "count": len(rows), "chapters": rows}


@router.get("/chapters/{number}")
def get_chapter(number: int, dir: str) -> dict:
    path = book_dir(dir)
    entry = chapters.read_index_entry(path, number)
    if not entry:
        raise HTTPException(status_code=404, detail=f"没有第{number}章")
    try:
        text = chapters.read_chapter(path, number) or ""
    except FileNotFoundError as e:
        raise HTTPException(status_code=410, detail=str(e)) from e
    return {"entry": entry, "text": text, "chars": chapters.count_chars(text)}


@router.get("/bible")
def get_bible(dir: str) -> dict:
    path = book_dir(dir)
    bible = load_bible(path)
    bible["relations"] = effective_relations(path, bible)
    return {"dir": str(path), "bible": bible}


@router.get("/ledger/{name}")
def get_ledger(name: str, dir: str, folded: bool = False) -> dict:
    if name not in LEDGER_KEYS:
        raise HTTPException(status_code=404, detail=f"未知账本：{name}")
    rows = read_jsonl(project_path(book_dir(dir), LEDGER[name]))
    if not folded:
        return {"name": name, "rows": rows}
    rows = _FOLDS[name](rows) if name in _FOLDS else rows
    return {"name": name, "count": len(rows), "rows": rows}


@router.get("/layout")
def get_layout() -> dict:
    """What the file layer expects on disk (store README companion)."""
    return {"layout": LAYOUT, "ledger": LEDGER, "chaptersPattern": "chapters/{NNN}-{title}.md"}
