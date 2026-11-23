"""Shared request helpers."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from ..core.paths import resolve_book


def book_dir(dir: str | None) -> Path:
    try:
        return resolve_book(dir or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
