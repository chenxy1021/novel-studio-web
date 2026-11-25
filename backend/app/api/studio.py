"""开书流水线：选题 / 大纲世界观 / 设定 / 伏笔 / 细纲与正文 / 参考包 / 段落 / 卷。"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException

from ..domain import (
    blueprint,
    concepts,
    foreshadow_gen,
    map_gen,
    references,
    relation_gen,
    runs,
    settings_gen,
    writing,
)
from ..domain.segment import plan_segment
from ..llm import LLMError
from ..store import append_jsonl
from ..store.paths import project_path as _project_path
from ..domain.memory import load_volumes
from . import streaming
from .deps import book_dir
from .errors import raise_generation, raise_review, stamp
from .schemas import (
    BatchOutlineBody,
    BlueprintBody,
    ConceptBody,
    ForeshadowGenBody,
    GenerateChapterBody,
    MapBody,
    OutlineBody,
    ProseBody,
    ReferenceBody,
    SegmentBody,
    SettingsBody,
    SupplementBody,
)

router = APIRouter(prefix="/projects", tags=["projects"])


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
        raise_review(e)
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
        raise_review(e)
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
        raise_review(e)
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
        raise_review(e)
        raise


@router.get("/map")
def get_map(dir: str) -> dict:
    """读这本书上次生成的地图；没画过就返回空 svg。"""
    return map_gen.load_map(book_dir(dir))


@router.post("/map")
def draw_map(body: MapBody, dir: str) -> dict:
    """按 bible.locations 起提示词，让模型画一张独立 SVG 并落盘。"""
    try:
        return map_gen.generate_map(book_dir(dir), model=body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
        raise


@router.get("/relations/graph")
def get_relation_graph(dir: str) -> dict:
    """读这本书上次生成的人物关系图；没画过就返回空 svg。"""
    return relation_gen.load_relation_map(book_dir(dir))


@router.post("/relations/graph")
def draw_relation_graph(body: MapBody, dir: str) -> dict:
    """按 bible 人物 + 已合并的关系起提示词，让模型画一张独立 SVG 并落盘。"""
    try:
        return relation_gen.generate_relation_map(book_dir(dir), model=body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
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
        raise_review(e)
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
        raise_review(e)
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
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
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


@router.post("/outlines/batch")
def generate_outlines_batch(body: BatchOutlineBody, dir: str) -> dict:
    """一批章节一次出细纲；整批已有可用细纲且 force=false 时复用。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    try:
        runs.acquire(path, run_id, body.from_chapter, "outline")
        try:
            return writing.generate_outlines(
                path,
                frm=body.from_chapter,
                to=body.to_chapter,
                model=body.model,
                force=body.force,
                style_override=body.styleOverride,
                skills_override=body.skills,
                focus=[f.model_dump() for f in body.focus],
            )
        finally:
            runs.release(path, run_id)
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
        raise


@router.post("/outlines/batch/stream")
def generate_outlines_batch_stream(body: BatchOutlineBody, dir: str):
    """同 `/outlines/batch`，流式返回细纲 JSON 原文。"""
    path = book_dir(dir)
    run_id = body.runId or f"adhoc-{uuid.uuid4().hex[:12]}"
    focus = [f.model_dump() for f in body.focus]

    def work(emit: streaming.Emit) -> None:
        runs.acquire(path, run_id, body.from_chapter, "outline")
        try:
            result = writing.generate_outlines(
                path,
                frm=body.from_chapter,
                to=body.to_chapter,
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
    except Exception as e:  # noqa: BLE001
        raise_generation(e)
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
    append_jsonl(_project_path(root, "ledger/segments.jsonl"), {
        "kind": "segment", "from": plan["from"], "to": plan["to"], "plan": plan, "at": stamp(),
    })
    return {"ok": True, "segment": plan}


@router.post("/segments/delete")
def delete_segment(body: SegmentBody, dir: str) -> dict:
    append_jsonl(_project_path(book_dir(dir), "ledger/segments.jsonl"),
                 {"op": "delete", "from": body.from_chapter, "to": body.to_chapter or body.from_chapter, "at": stamp()})
    return {"ok": True}


@router.get("/volumes")
def get_volumes(dir: str) -> dict:
    path = book_dir(dir)
    return {"dir": str(path), "volumes": load_volumes(path)}
