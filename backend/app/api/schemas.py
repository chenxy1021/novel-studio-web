"""Request / response bodies shared by the ``/api/projects`` routers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class MapBody(BaseModel):
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


class BatchOutlineBody(OutlineBody):
    """一批章节共用一次细纲生成（from/to 连续章号）。"""

    from_chapter: int = Field(alias="from")
    to_chapter: int = Field(alias="to")

    model_config = {"populate_by_name": True}


class ProseBody(BaseModel):
    overwrite: bool = False
    styleOverride: dict[str, Any] | None = None
    skills: dict[str, bool] | None = None
    focus: list[FocusRef] = Field(default_factory=list)
    model: str | None = None
    # 1–3：并排写几稿再挑；只对非流式生效。
    candidates: int = 1
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
    # 已写到第几章（章节索引最大章号）与下一章章号；currentChapter 是它的旧名。
    writtenThrough: int = 0
    nextChapter: int = 1
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


class RewriteFinding(BaseModel):
    """作者屏幕上正看着的体检条目（确定性 + AI 复检），改写时一起塞进提示词。"""

    severity: str = "mid"
    code: str = ""
    message: str = ""
    hint: str = ""
    source: str = ""
    # 复检条目带的证据：quote 是本章原句，basis 是前情/细纲依据。
    # 段落重写靠 quote 找到要改的那一段，也靠它验证改完还在不在。
    quote: str = ""
    basis: str = ""
    paragraph: int = 0


class ResolveAiBody(BaseModel):
    """作者确认某条复检问题已解决（或不再处理）。"""

    code: str = ""
    message: str
    how: str = "manual"


class DismissCheckBody(BaseModel):
    """作者确认某条确定性体检是误报；命中句按 quote/行号定位。"""

    code: str = ""
    message: str = ""
    quote: str = ""
    line: int = 0
    offset: int = 0


class ParagraphRewriteBody(BaseModel):
    """只重写一段：段落号来自复检条目的定位，finding 是那一条问题。"""

    paragraph: int
    instruction: str = ""
    model: str | None = None
    finding: RewriteFinding | None = None


class RewriteBody(BaseModel):
    reason: str = ""
    instruction: str = ""
    model: str | None = None
    # Slice 4: which rewrite skills the author ticked. Omitted -> backend
    # preselects from the deterministic check result.
    skills: list[str] | None = None
    # 体检/复检出的问题。后端自己也会重跑确定性体检，这里补的是 AI 复检那一层
    # 以及作者刚看过的条目，避免「点重写时问题没进提示词」。
    findings: list[RewriteFinding] | None = None
    # 作者在改写弹窗里取消勾选的问题。后端会把本轮 AI 复检没过的条目补进提示词，
    # 这里列出来的不再塞回去——取消勾选就是明确不要。
    dismissed: list[str] = Field(default_factory=list)
    # 只用于 AI 复检：True 时忽略「同一份输入沿用上次结论」的缓存，强制重跑。
    force: bool = False


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
    # 多跑一次模型核对到期伏笔（正文已收的自动记账）。页面上的「按批体检」打开；
    # 默认关，纯确定性体检仍然秒回、可离线跑。
    verify: bool = False

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


class ForeshadowIdBody(BaseModel):
    id: str


class AbandonBody(BaseModel):
    id: str
    note: str = ""
