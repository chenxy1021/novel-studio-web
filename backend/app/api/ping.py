from __future__ import annotations

from fastapi import APIRouter

from ..store.paths import LEDGER, projects_root

router = APIRouter(tags=["meta"])


@router.get("/ping")
def ping() -> dict:
    return {
        "ok": True,
        "app": "novel-web",
        "version": "0.1.0",
        "projectsDir": str(projects_root()),
        "ledgers": sorted(LEDGER),
    }
