"""Stable domain errors for the writing slice.

Each error carries the machine code / HTTP status the API layer emits, so routes can
map them to the unified error body::

    {"detail": {"code": "...", "message": "...", "retryable": true, "findings": []}}

They all subclass ``ValueError`` so older call sites that catch ``ValueError`` keep
working (legacy ``generate_chapter`` did).
"""

from __future__ import annotations

from typing import Any


class DomainError(ValueError):
    code = "DOMAIN_ERROR"
    status_code = 400
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        findings: list[dict[str, Any]] | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        self.findings = findings or []
        self.field = field


class WritingError(DomainError):
    code = "WRITE_ERROR"


class NoOutlineError(WritingError):
    code = "NO_OUTLINE"


class ChapterOutOfRange(WritingError):
    code = "CHAPTER_OUT_OF_RANGE"
    status_code = 404


class ChapterExists(WritingError):
    code = "CHAPTER_EXISTS"
    status_code = 409


class NoOutlineRow(WritingError):
    code = "NO_OUTLINE_ROW"
    status_code = 409


class NoForeshadowError(WritingError):
    """开写前必须先设计伏笔：正文要按伏笔网推进，空着写会一路丢线。"""

    code = "NO_FORESHADOW"
    status_code = 409


class ProseTooShort(WritingError):
    code = "PROSE_TOO_SHORT"
    status_code = 502


class WriteBusy(WritingError):
    code = "WRITE_BUSY"
    status_code = 409
    retryable = True


class StyleInvalid(DomainError):
    code = "STYLE_INVALID"


class SkillInvalid(DomainError):
    code = "SKILL_INVALID"


class SkillUnavailable(DomainError):
    code = "SKILL_UNAVAILABLE"
