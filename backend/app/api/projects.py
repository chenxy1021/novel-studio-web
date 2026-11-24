"""Book listing, read metadata, and the review write loop (archive / reject / rewrite)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.paths import books_root, book_summary, delete_book, list_books, recent_books
from ..domain import blueprint, concepts, create, foreshadow_gen, memory, memory_gen, nuewen, review, references, runs, settings_gen, writing
from ..domain import skills as skills_mod
from ..domain import style as style_mod
from ..domain import style_presets
from ..domain.errors import DomainError, StyleInvalid
from ..domain.segment import plan_segment
from ..store import append_jsonl
from ..store.paths import project_path as _project_path
from ..domain.memory import load_volumes
from ..llm import LLMError
from ..store import chapter as chapters
from ..store import load_bible, load_project, project_lock, save_bible, save_project
from ..store.jsonl import fold_by_key, fold_foreshadow, fold_outline, fold_segments, fold_timeline, read_jsonl
from ..store.paths import LEDGER, LAYOUT, LEDGER_KEYS, project_path
from . import streaming
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


class DeleteBookBody(BaseModel):
    dir: str = Field(..., description="绝对路径")
    confirm: str = Field("", description="书名，二次确认")


class CreateBookBody(BaseModel):
    title: str
    genre: str = ""
    platform: str = "generic"
    targetChapters: int = 100
    wordsPerChapter: int = 0
    logline: str = ""
    synopsis: str = ""
    theme: str = ""
    tone: str = ""
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    selectedConceptId: str = ""
    nuewen: bool = False


class ConceptBody(BaseModel):
    direction: str = ""
    genre: str = ""
    logline: str = ""
    platform: str = "generic"
    targetChapters: int = 0
    wordsPerChapter: int = 0
    count: int = 3
    avoid: list[str] = Field(default_factory=list)
    nuewen: bool = False
    model: str | None = None


class BlueprintBody(BaseModel):
    """生成大纲 + 世界观；nuewen 不传就沿用建书时的选择。"""
    nuewen: bool | None = None
    model: str | None = None


class SettingsBody(BaseModel):
    model: str | None = None


class SupplementBody(BaseModel):
    """写后补设定：看最近 recent 章正文，只补没有的条目。"""
    recent: int = Field(8, ge=1, le=60)
    model: str | None = None


class StyleBody(BaseModel):
    """Accepts ``{"style": {...}}`` or a bare ``{...}`` partial style body."""
    model_config = {"extra": "allow"}
    style: Any = None


class SkillsBody(BaseModel):
    """Accepts ``{"skills": {...}}`` or a bare ``{...}`` switch body."""
    model_config = {"extra": "allow"}
    skills: Any = None


class PresetBody(BaseModel):
    id: str = ""
    overwrite: bool = False


class ForeshadowGenBody(BaseModel):
    count: int | None = None
    model: str | None = None


class MemoryGenBody(BaseModel):
    force: bool = False
    model: str | None = None


class MemoryBatchBody(BaseModel):
    from_chapter: int | None = Field(default=None, alias="from")
    to_chapter: int | None = Field(default=None, alias="to")
    force: bool = False
    model: str | None = None

    model_config = {"populate_by_name": True}


class GenerateChapterBody(BaseModel):
    model: str | None = None
    overwrite: bool = False
    reuseOutline: bool = True


class FocusRef(BaseModel):
    type: str = ""
    key: str = ""
    label: str = ""


class OutlineBody(BaseModel):
    force: bool = False
    styleOverride: dict[str, Any] | None = None
    skills: dict[str, bool] | None = None
    focus: list[FocusRef] = Field(default_factory=list)
    model: str | None = None
    runId: str | None = None


class ProseBody(BaseModel):
    overwrite: bool = False
    styleOverride: dict[str, Any] | None = None
    skills: dict[str, bool] | None = None
    focus: list[FocusRef] = Field(default_factory=list)
    model: str | None = None
    runId: str | None = None


class ReferenceBody(BaseModel):
    """Preview the pack with per-chapter focus; nothing is generated or written."""
    focus: list[FocusRef] = Field(default_factory=list)
    stage: str = "prose"
    skills: dict[str, bool] | None = None



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
    platform: str = ""
    logline: str = ""
    synopsis: str = ""
    theme: str = ""
    tone: str = ""
    targetChapters: int = 0
    currentChapter: int = 0
    wordsPerChapter: int = 0
    minChars: int = 0
    segmentSize: int = 10
    updatedAt: str = ""
    gate: dict[str, Any] = Field(default_factory=dict)
    gates: dict[str, Any] = Field(default_factory=dict)
    spine: str = ""
    outlineText: str = ""
    worldText: str = ""
    nuewen: bool = False
    outlineAt: str = ""
    settingsAt: str = ""
    foreshadowAt: str = ""
    chapters: list[ChapterMeta] = Field(default_factory=list)
    openForeshadow: int = 0
    pending: list[int] = Field(default_factory=list)


class BookSettingsBody(BaseModel):
    """设置页「写作与存档」里可改的两项；None 表示这次不动。"""
    minChars: int | None = None
    segmentSize: int | None = None


class ArchiveBody(BaseModel):
    force: bool = False


class RejectBody(BaseModel):
    reason: str = ""


class SaveChapterBody(BaseModel):
    text: str
    title: str | None = None
    unapprove: bool = True


class RewriteBody(BaseModel):
    reason: str = ""
    instruction: str = ""
    model: str | None = None
    # Slice 4: which rewrite skills the author ticked. Omitted -> backend
    # preselects from the deterministic check result.
    skills: list[str] | None = None


class NuewenBody(BaseModel):
    instruction: str = ""
    model: str | None = None


class NuewenModeBody(BaseModel):
    enabled: bool


class SegmentBody(BaseModel):
    from_chapter: int = Field(alias="from")
    to_chapter: int | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


class BatchBody(BaseModel):
    from_chapter: int | None = Field(default=None, alias="from")
    to_chapter: int | None = Field(default=None, alias="to")

    model_config = {"populate_by_name": True}


class ForeshadowBody(BaseModel):
    name: str = ""
    kind: str = "detail"
    plantedChapter: int = 0
    dueChapter: int | None = None
    revealWho: str = ""
    hint: str = ""


class PayoffBody(BaseModel):
    id: str
    chapter: int


@router.get("")
def get_projects() -> dict:
    return {"root": str(books_root()), "books": list_books(), "recent": recent_books()}


@router.get("/platforms")
def get_platforms() -> dict:
    return {"platforms": create.list_platforms()}


@router.get("/style")
def get_style(dir: str) -> dict:
    """本书文风 v2 + 平台默认值；旧字段原样兼容，缺字段按空处理。"""
    path = book_dir(dir)
    project = load_project(path) or {}
    bible = load_bible(path)
    stored = bible.get("style")
    return {
        "style": style_mod.normalize_style(stored),
        "defaults": style_mod.platform_default_style(project.get("platform")),
        "source": "book" if style_mod.has_values(stored) else "platform",
        "autoGenerated": bool(isinstance(stored, dict) and stored.get("autoGenerated")),
    }


@router.put("/style")
def put_style(body: StyleBody, dir: str) -> dict:
    """部分合并：只改提交的字段，未提交字段保持原值；version 自动置 2。"""
    path = book_dir(dir)
    patch = body.style if body.style is not None else body.model_dump(exclude={"style"}, exclude_none=True)
    try:
        style_mod.validate_patch(patch)
    except DomainError as e:
        _raise_domain(e)
    with project_lock(path):
        bible = load_bible(path)
        merged = style_mod.merge_style(bible.get("style"), patch)
        bible["style"] = merged
        save_bible(path, bible)
    return {"ok": True, "style": merged, "updatedAt": merged.get("updatedAt") or ""}


@router.get("/style/presets")
def list_style_presets() -> dict:
    """8 个作家文风预设；全部 applicable，可直接用于正文。"""
    return {"presets": style_presets.list_presets()}


@router.post("/style/preset")
def apply_style_preset(body: PresetBody, dir: str) -> dict:
    """套用预设：默认只补空字段；overwrite=true 覆盖预设维度。

    样章随预设切换：本书没有样章，或现有样章全部来自预设时，换成这位作家的样章；
    作者手填/编辑过的样章一律保留。
    """
    path = book_dir(dir)
    preset = style_presets.get_preset(body.id)
    if preset is None:
        _raise_domain(StyleInvalid(f"未知的文风预设：{body.id}", field="id"))
    fields = preset.get("fields") if isinstance(preset.get("fields"), dict) else {}
    with project_lock(path):
        bible = load_bible(path)
        current = style_mod.normalize_style(bible.get("style"))
        patch: dict[str, Any] = {}
        for key, value in fields.items():
            if key == "samples":
                continue
            empty = current.get(key) in (None, "", [], {})
            if body.overwrite or empty:
                patch[key] = value
        # 样章不是「拆」出来的：空样章或全为预设样章时随作家切换；
        # 旧数据没有 origin，用正文是否命中任一预设样章来识别。
        current_samples = current.get("samples") or []
        known = style_presets.preset_sample_texts()

        def from_preset(sample: Any) -> bool:
            if not isinstance(sample, dict):
                return False
            if sample.get("origin") == "preset":
                return True
            return str(sample.get("text") or "").strip() in known

        incoming = style_presets.preset_samples(preset)
        if not current_samples:
            if incoming:
                patch["samples"] = incoming
        elif any(from_preset(s) for s in current_samples):
            # 保住手填/编辑过的，换掉旧的预设样章，再补上这位作家的一段。
            kept = [s for s in current_samples if not from_preset(s)]
            patch["samples"] = (kept + incoming)[: style_mod.LIMITS["samples"]]
        patch["presetId"] = preset["id"]
        merged = style_mod.merge_style(bible.get("style"), patch)
        bible["style"] = merged
        save_bible(path, bible)
    view = {**preset, "samples": style_presets.preset_samples(preset)}
    return {"ok": True, "style": merged, "preset": view}


@router.get("/writing-skills")
def get_writing_skills(dir: str) -> dict:
    """八个技能开关；首次读取用默认，nuewen 跟随书的虐文模式。"""
    path = book_dir(dir)
    project = load_project(path) or {}
    bible = load_bible(path)
    return {
        "skills": skills_mod.read_skills(project),
        "availability": skills_mod.availability(project, bible),
        "updatedAt": skills_mod.updated_at(project),
    }


@router.put("/writing-skills")
def put_writing_skills(body: SkillsBody, dir: str) -> dict:
    """只合并传入的键；未知键 400；非虐文书 nuewen 强制 false。"""
    path = book_dir(dir)
    patch = body.skills if body.skills is not None else body.model_dump(exclude={"skills"}, exclude_none=True)
    with project_lock(path):
        project = load_project(path) or {}
        try:
            merged = skills_mod.merge_skills(project, patch)
        except DomainError as e:
            _raise_domain(e)
        at = skills_mod.stamp(project, merged)
        save_project(path, project)
    return {"ok": True, "skills": merged, "updatedAt": at}


@router.post("/concepts")
def make_concepts(body: ConceptBody) -> dict:
    try:
        return concepts.generate_concepts(
            direction=body.direction,
            genre=body.genre,
            logline=body.logline,
            platform=body.platform,
            target_chapters=body.targetChapters,
            words_per_chapter=body.wordsPerChapter,
            count=body.count,
            avoid=body.avoid,
            nuewen=body.nuewen,
            model=body.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/blueprint")
def make_blueprint(body: BlueprintBody, dir: str) -> dict:
    """选题之后：由故事梗概一次生成大纲 + 世界观（虐文模式自动带公式）。"""
    try:
        return blueprint.generate_blueprint(
            book_dir(dir), nuewen=body.nuewen, model=body.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/blueprint/stream")
def make_blueprint_stream(body: BlueprintBody, dir: str):
    """同 `/blueprint`，但把模型边写边推：阶段 + 增量正文 + 最终结果。"""
    path = book_dir(dir)
    nuewen, model = body.nuewen, body.model

    def work(emit: streaming.Emit) -> None:
        result = blueprint.generate_blueprint(
            path, nuewen=nuewen, model=model,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.put("/book")
def put_book_settings(body: BookSettingsBody, dir: str) -> dict:
    """改书级写作参数：每章字数硬下限、批量写作每段章数。只写这两个键。"""
    path = book_dir(dir)
    patch: dict[str, Any] = {}
    if body.minChars is not None:
        if not 0 <= body.minChars <= 20000:
            raise _bad_request("每章字数下限要在 0–20000 之间")
        patch["minChars"] = int(body.minChars)
    if body.segmentSize is not None:
        if not 3 <= body.segmentSize <= 30:
            raise _bad_request("每段章数要在 3–30 之间")
        patch["segmentSize"] = int(body.segmentSize)
    if not patch:
        raise _bad_request("没有要改的字段")
    with project_lock(path):
        project = load_project(path)
        if not project:
            raise _bad_request("不是小说项目（缺 project.json）")
        project.update(patch)
        project["updatedAt"] = _stamp()
        save_project(path, project)
    return {
        "ok": True,
        "minChars": review.chapter_min_chars(project),
        "segmentSize": max(3, min(30, int(project.get("segmentSize") or 10))),
    }


@router.post("/settings/stream")
def make_settings_stream(body: SettingsBody, dir: str):
    """同 `/settings`：人物 / 势力地点 / 规则物品 / 世界纵深四段边拆边推。"""
    path = book_dir(dir)
    model = body.model

    def work(emit: streaming.Emit) -> None:
        result = settings_gen.generate_settings(
            path, model=model,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/settings")
def make_settings(body: SettingsBody, dir: str) -> dict:
    """由大纲 + 世界观拆出人物 / 势力 / 地点 / 物品 / 规则 / 文风，写进 bible.json。"""
    try:
        return settings_gen.generate_settings(book_dir(dir), model=body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/settings/supplement/stream")
def supplement_settings_stream(body: SupplementBody, dir: str):
    """同 `/settings/supplement`：读最近正文 → 补新设定，边推边看。"""
    path = book_dir(dir)
    recent, model = body.recent, body.model

    def work(emit: streaming.Emit) -> None:
        result = settings_gen.supplement_settings(
            path, recent=recent, model=model,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/settings/supplement")
def supplement_settings(body: SupplementBody, dir: str) -> dict:
    """写完一批后：只从最近正文里补新出现的人物/地点/物品/势力/规则，不重复。"""
    try:
        return settings_gen.supplement_settings(
            book_dir(dir), recent=body.recent, model=body.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/foreshadow/generate/stream")
def generate_foreshadows_stream(body: ForeshadowGenBody, dir: str):
    """同 `/foreshadow/generate`：整套伏笔边设计边推，最后落账。"""
    path = book_dir(dir)
    count, model = body.count, body.model

    def work(emit: streaming.Emit) -> None:
        result = foreshadow_gen.generate_foreshadows(
            path, count=count, model=model,
            on_delta=lambda text: emit({"type": "delta", "text": text}),
            on_stage=lambda label: emit({"type": "stage", "label": label}),
        )
        emit({"type": "done", "result": result})

    return streaming.sse_response(work)


@router.post("/foreshadow/generate")
def generate_foreshadows(body: ForeshadowGenBody, dir: str) -> dict:
    """由大纲 + 世界观 + 设定设计整套伏笔与草蛇灰线，落 ledger/foreshadow.jsonl。"""
    try:
        return foreshadow_gen.generate_foreshadows(book_dir(dir), count=body.count, model=body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/chapters/{number}/generate")
def generate_chapter(number: int, body: GenerateChapterBody, dir: str) -> dict:
    """兼容包装：先出本章细纲，再照细纲写正文（落盘为待确认）。"""
    try:
        return writing.generate_chapter(
            book_dir(dir),
            number=number,
            model=body.model,
            overwrite=body.overwrite,
            reuse_outline=body.reuseOutline,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/chapters/{number}/outline")
def generate_outline(number: int, body: OutlineBody, dir: str) -> dict:
    """只生成细纲；已有可用细纲且 force=false 时复用，不调模型。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    try:
        runs.acquire(path, run_id, number, "outline")
        try:
            return writing.generate_outline(
                path,
                number=number,
                model=body.model,
                force=body.force,
                style_override=body.styleOverride,
                skills_override=body.skills,
                focus=[f.model_dump() for f in body.focus],
            )
        finally:
            runs.release(path, run_id)
    except DomainError as e:
        _raise_domain(e)
    except LLMError as e:
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    except TimeoutError as e:
        raise HTTPException(status_code=409, detail={
            "code": "WRITE_TIMEOUT", "message": str(e), "retryable": True,
        }) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    raise


@router.post("/chapters/{number}/outline/stream")
def generate_outline_stream(number: int, body: OutlineBody, dir: str):
    """同 `/outline`，流式返回细纲原文（含机器块，前端只展示其中 Markdown）。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    focus = [f.model_dump() for f in body.focus]

    def work(emit: streaming.Emit) -> None:
        runs.acquire(path, run_id, number, "outline")
        try:
            result = writing.generate_outline(
                path,
                number=number,
                model=body.model,
                force=body.force,
                style_override=body.styleOverride,
                skills_override=body.skills,
                focus=focus,
                on_delta=lambda text: emit({"type": "delta", "text": text}),
                on_stage=lambda label: emit({"type": "stage", "label": label}),
            )
            emit({"type": "done", "result": result})
        finally:
            runs.release(path, run_id)

    return streaming.sse_response(work)


@router.post("/chapters/{number}/prose")
def generate_prose(number: int, body: ProseBody, dir: str) -> dict:
    """照细纲写正文；失败不落盘，成功一律 approved=false。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    try:
        runs.acquire(path, run_id, number, "prose")
        try:
            return writing.generate_prose(
                path,
                number=number,
                model=body.model,
                overwrite=body.overwrite,
                style_override=body.styleOverride,
                skills_override=body.skills,
                focus=[f.model_dump() for f in body.focus],
            )
        finally:
            runs.release(path, run_id)
    except DomainError as e:
        _raise_domain(e)
    except LLMError as e:
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    except TimeoutError as e:
        raise HTTPException(status_code=409, detail={
            "code": "WRITE_TIMEOUT", "message": str(e), "retryable": True,
        }) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    raise


@router.post("/chapters/{number}/prose/stream")
def generate_prose_stream(number: int, body: ProseBody, dir: str):
    """同 `/prose`，流式返回正文；补写与记忆回写会先推一条阶段事件。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    focus = [f.model_dump() for f in body.focus]

    def work(emit: streaming.Emit) -> None:
        runs.acquire(path, run_id, number, "prose")
        try:
            result = writing.generate_prose(
                path,
                number=number,
                model=body.model,
                overwrite=body.overwrite,
                style_override=body.styleOverride,
                skills_override=body.skills,
                focus=focus,
                on_delta=lambda text: emit({"type": "delta", "text": text}),
                on_stage=lambda label: emit({"type": "stage", "label": label}),
            )
            emit({"type": "done", "result": result})
        finally:
            runs.release(path, run_id)

    return streaming.sse_response(work)


@router.get("/chapters/{number}/references")
def chapter_references(number: int, dir: str, stage: str = "prose", skills: str | None = None) -> dict:
    """The exact pack injected when generating this chapter: counts match the prompt."""
    try:
        chosen = json.loads(skills) if skills else None
        if chosen is not None and not isinstance(chosen, dict):
            raise ValueError("skills 必须是 {技能: 布尔值} 对象")
        pack = references.build_reference_pack(
            book_dir(dir), number, stage=stage, skills=chosen,
        )
        pack["stage"] = stage
        pack["prompt"] = references.render_reference_block(pack, stage=stage)
        return pack
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e


@router.post("/chapters/{number}/references/preview")
def preview_chapter_references(number: int, body: ReferenceBody, dir: str) -> dict:
    """Recompute the pack with this chapter's extra focus; still read-only."""
    try:
        pack = references.build_reference_pack(
            book_dir(dir), number,
            focus=[f.model_dump() for f in body.focus],
            stage=body.stage,
            skills=body.skills,
        )
        pack["stage"] = body.stage
        pack["prompt"] = references.render_reference_block(pack, stage=body.stage)
        return pack
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e


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
        deleted = delete_book(body.dir, expect_title=body.confirm)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True, "deleted": str(deleted)}


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
    found = memory.recall_memory(book_dir(dir), query=q, frm=frm, to=to)
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
        _raise_memory(e)
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
        _raise_memory(e)
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
                raise _bad_request("还没有可生成记忆的正文")
            by_chapter = memory.load_memory_rows(path)["byChapter"]
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
        _raise_memory(e)
        raise
    return {"ok": True, **result}


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
        platform=project.get("platform") or "",
        logline=project.get("logline") or "",
        synopsis=project.get("synopsis") or "",
        theme=project.get("theme") or "",
        tone=project.get("tone") or "",
        targetChapters=int(project.get("targetChapters") or 0),
        currentChapter=int(project.get("currentChapter") or 0),
        wordsPerChapter=int(project.get("wordsPerChapter") or 0),
        minChars=review.chapter_min_chars(project),
        segmentSize=max(3, min(30, int(project.get("segmentSize") or 10))),
        updatedAt=str(project.get("updatedAt") or ""),
        gate=project.get("gate") or {},
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


def _raise_domain(e: DomainError) -> None:
    """统一错误体：{code, message, retryable?, findings?, field?}。"""
    detail: dict[str, Any] = {"code": e.code, "message": str(e)}
    if e.retryable:
        detail["retryable"] = True
    if e.findings:
        detail["findings"] = e.findings
    if e.field:
        detail["field"] = e.field
    raise HTTPException(status_code=e.status_code, detail=detail) from e


def _raise_memory(e: Exception) -> None:
    """记忆生成错误映射：模型问题 502，忙/超时 409，其余按领域错误/400。"""
    if isinstance(e, LLMError):
        raise HTTPException(status_code=502, detail={"code": "LLM_ERROR", "message": str(e)}) from e
    if isinstance(e, TimeoutError):
        raise HTTPException(status_code=409, detail={
            "code": "WRITE_TIMEOUT", "message": str(e), "retryable": True,
        }) from e
    if isinstance(e, DomainError):
        _raise_domain(e)
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}) from e
    raise e


def _raise_review(e: Exception) -> None:
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


@router.get("/chapters/{number}/check")
def check_chapter(number: int, dir: str) -> dict:
    try:
        return review.check_chapter(book_dir(dir), number)
    except Exception as e:  # noqa: BLE001 - mapped to HTTP below
        _raise_review(e)
        raise


@router.post("/check-batch")
def check_batch(body: BatchBody, dir: str) -> dict:
    try:
        return review.check_batch(book_dir(dir), body.from_chapter, body.to_chapter)
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/chapters/{number}/archive")
def archive_chapter(number: int, body: ArchiveBody, dir: str) -> dict:
    try:
        return review.archive_chapter(book_dir(dir), number, force=body.force)
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": message})


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@router.post("/archive-batch")
def archive_batch(body: dict[str, Any], dir: str) -> dict:
    """批量存档：逐章复用 archive_chapter；单章失败不影响其他章，整批 200。"""
    path = book_dir(dir)
    project = load_project(path) or {}

    raw = body.get("numbers")
    if not isinstance(raw, list) or not raw:
        raise _bad_request("numbers 必须是非空整数数组")
    numbers: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _bad_request("numbers 必须是非空整数数组")
        if value not in numbers:
            numbers.append(value)

    force = body.get("force", False)
    if not isinstance(force, bool):
        raise _bad_request("force 必须是布尔值")

    target = int(project.get("targetChapters") or 0)
    for number in numbers:
        if number < 1 or (target and number > target):
            raise _bad_request(f"章号超出范围：{number}")

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
            except review.ChapterConflict as e:
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
        _raise_review(e)
        raise


@router.put("/chapters/{number}")
def save_chapter(number: int, body: SaveChapterBody, dir: str) -> dict:
    try:
        return review.save_chapter_text(
            book_dir(dir), number, body.text, title=body.title, unapprove=body.unapprove,
        )
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
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
        _raise_review(e)
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
        _raise_review(e)
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
        _raise_review(e)
        raise


@router.post("/foreshadow/payoff")
def payoff_foreshadow(body: PayoffBody, dir: str) -> dict:
    try:
        return review.payoff_foreshadow(book_dir(dir), body.id, body.chapter)
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.get("/nuewen")
def get_nuewen(dir: str) -> dict:
    return nuewen.read_plan(book_dir(dir))


@router.post("/nuewen/mode")
def set_nuewen_mode(body: NuewenModeBody, dir: str) -> dict:
    try:
        return nuewen.set_mode(book_dir(dir), body.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/nuewen/plan")
def make_nuewen_plan(body: NuewenBody, dir: str) -> dict:
    try:
        return nuewen.generate_plan(book_dir(dir), instruction=body.instruction, model=body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
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
        _raise_review(e)
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
        _raise_review(e)
        raise


@router.post("/discarded/purge")
def purge_discarded(body: dict, dir: str) -> dict:
    try:
        return review.purge_discarded(book_dir(dir), str(body.get("draftFile") or ""))
    except Exception as e:  # noqa: BLE001
        _raise_review(e)
        raise


@router.post("/segments/plan")
def preview_segment(body: SegmentBody, dir: str) -> dict:
    try:
        return plan_segment(book_dir(dir), frm=body.from_chapter, to=body.to_chapter)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/segments")
def save_segment(body: SegmentBody, dir: str) -> dict:
    root = book_dir(dir)
    try:
        plan = plan_segment(root, frm=body.from_chapter, to=body.to_chapter)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    from datetime import datetime, timezone

    at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    append_jsonl(_project_path(root, "ledger/segments.jsonl"), {
        "kind": "segment", "from": plan["from"], "to": plan["to"], "plan": plan, "at": at,
    })
    return {"ok": True, "segment": plan}


@router.post("/segments/delete")
def delete_segment(body: SegmentBody, dir: str) -> dict:
    from datetime import datetime, timezone

    at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    append_jsonl(_project_path(book_dir(dir), "ledger/segments.jsonl"),
                 {"op": "delete", "from": body.from_chapter, "to": body.to_chapter or body.from_chapter, "at": at})
    return {"ok": True}


@router.get("/volumes")
def get_volumes(dir: str) -> dict:
    path = book_dir(dir)
    return {"dir": str(path), "volumes": load_volumes(path)}


@router.get("/layout")
def get_layout() -> dict:
    """What the file layer expects on disk (store README companion)."""
    return {"layout": LAYOUT, "ledger": LEDGER, "chaptersPattern": "chapters/{NNN}-{title}.md"}
