"""Book listing and read-only metadata. Write endpoints arrive with the domain migration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.paths import books_root, book_summary, list_books, recent_books
from ..store import chapter as chapters
from ..store import load_bible, load_project
from ..store.jsonl import fold_by_key, fold_foreshadow, fold_outline, fold_segments, fold_timeline, read_jsonl
from ..store.paths import LEDGER, LAYOUT, LEDGER_KEYS, project_path
from .deps import book_dir

router = APIRouter(prefix="/projects", tags=["projects"])

_FOLDS = {
    "foreshadow": fold_foreshadow,
    "segments": fold_segments,
    "outline": fold_outline,
    "timeline": fold_timeline,
    "dismissed": lambda rows: fold_by_key(rows, "key"),
}


class OpenBook(BaseModel):
    dir: str = Field(..., description="绝对路径")


class ChapterMeta(BaseModel):
    number: int
    title: str = ""
    chars: int = 0
    approved: bool = False
    chapterVerdict: str = "pass"
    endHook: dict[str, Any] | None = None


class BookOverview(BaseModel):
    dir: str
    title: str
    genre: str = ""
    logline: str = ""
    synopsis: str = ""
    targetChapters: int = 0
    currentChapter: int = 0
    wordsPerChapter: int = 0
    gate: dict[str, Any] = Field(default_factory=dict)
    chapters: list[ChapterMeta] = Field(default_factory=list)
    openForeshadow: int = 0
    pending: list[int] = Field(default_factory=list)


@router.get("")
def get_projects() -> dict:
    return {"root": str(books_root()), "books": list_books(), "recent": recent_books()}


@router.post("/open")
def open_project(body: OpenBook) -> dict:
    return book_summary(book_dir(body.dir))


@router.get("/overview")
def project_overview(dir: str) -> BookOverview:
    path = book_dir(dir)
    project = load_project(path) or {}
    index = chapters.read_index(path)
    fs_rows = read_jsonl(project_path(path, LEDGER["foreshadow"]))
    return BookOverview(
        dir=str(path),
        title=project.get("title") or path.name,
        genre=project.get("genre") or "",
        logline=project.get("logline") or "",
        synopsis=project.get("synopsis") or "",
        targetChapters=int(project.get("targetChapters") or 0),
        currentChapter=int(project.get("currentChapter") or 0),
        wordsPerChapter=int(project.get("wordsPerChapter") or 0),
        gate=project.get("gate") or {},
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
    return {"dir": str(path), "bible": load_bible(path)}


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
