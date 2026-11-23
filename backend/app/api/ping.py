from __future__ import annotations

from fastapi import APIRouter

from ..store.paths import DEFAULT_PROJECTS_DIR, LEDGER

router = APIRouter(tags=["meta"])


@router.get("/ping")
def ping() -> dict:
    return {
        "ok": True,
        "app": "novel-web",
        "version": "0.1.0",
        "projectsDir": str(DEFAULT_PROJECTS_DIR),
        "ledgers": sorted(LEDGER),
    }
