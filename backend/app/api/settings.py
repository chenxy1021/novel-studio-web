"""模型出口配置：设置页读写 baseUrl / model，并能就地探活列出可用模型。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..llm import load_settings, ping_provider, save_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class ModelSettings(BaseModel):
    baseUrl: str | None = None
    model: str | None = None
    fastModel: str | None = None
    apiKey: str | None = None


@router.get("")
def read_settings() -> dict[str, Any]:
    return load_settings()


@router.put("")
def update_settings(patch: ModelSettings) -> dict[str, Any]:
    try:
        return save_settings(patch.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/probe")
def probe(patch: ModelSettings | None = None) -> dict[str, Any]:
    """拿页面上还没保存的值先探一次；没传就用已保存的。"""
    return ping_provider(patch.model_dump(exclude_none=True) if patch else None)
