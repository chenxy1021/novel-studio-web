"""写作技能开关：按书存 ``project.json.writingSkills``。

八个布尔开关，首次读取时用默认值；``nuewen`` 跟随 ``project.nuewen``，非虐文书强制 false。
本模块只做纯函数；路由层负责读写 project.json。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import SkillInvalid

SKILL_KEYS = (
    "deai",
    "dialogue",
    "scene",
    "hook",
    "continuity",
    "platform",
    "nuewen",
    "styleSamples",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_skills(project: dict[str, Any]) -> dict[str, bool]:
    """All on, except ``nuewen`` which follows the book's 虐文 mode."""
    skills = {key: True for key in SKILL_KEYS}
    skills["nuewen"] = bool(project.get("nuewen"))
    return skills


def read_skills(project: dict[str, Any]) -> dict[str, bool]:
    stored = project.get("writingSkills") if isinstance(project.get("writingSkills"), dict) else {}
    merged = default_skills(project)
    for key in SKILL_KEYS:
        if isinstance(stored.get(key), bool):
            merged[key] = stored[key]
    if not project.get("nuewen"):
        merged["nuewen"] = False
    return merged


def merge_skills(project: dict[str, Any], patch: Any) -> dict[str, bool]:
    """Merge only submitted known keys; unknown / non-boolean keys are a 400."""
    if not isinstance(patch, dict):
        raise SkillInvalid("skills 必须是对象", field="skills")
    unknown = [key for key in patch if key not in SKILL_KEYS]
    if unknown:
        raise SkillInvalid(f"未知技能：{'、'.join(str(x) for x in unknown)}", field="skills")
    for key, value in patch.items():
        if not isinstance(value, bool):
            raise SkillInvalid(f"技能 {key} 必须是布尔值", field=key)
    merged = read_skills(project)
    for key in SKILL_KEYS:
        if key in patch:
            merged[key] = bool(patch[key])
    if not project.get("nuewen"):
        merged["nuewen"] = False
    return merged


def availability(project: dict[str, Any], bible: dict[str, Any]) -> dict[str, dict[str, Any]]:
    style = bible.get("style") if isinstance(bible.get("style"), dict) else {}
    samples = style.get("samples") if isinstance(style.get("samples"), list) else []
    enabled = bool(project.get("nuewen"))
    return {
        "nuewen": {
            "enabled": enabled,
            "reason": "" if enabled else "这本书未开启虐文模式",
        },
        "styleSamples": {
            "enabled": True,
            "reason": "" if samples else "这本书还没有样章",
        },
    }


def updated_at(project: dict[str, Any]) -> str:
    return str(project.get("writingSkillsUpdatedAt") or "")


def stamp(project: dict[str, Any], skills: dict[str, bool]) -> str:
    """Persist the eight switches plus their save time; returns the timestamp."""
    at = _now()
    project["writingSkills"] = {key: bool(skills.get(key)) for key in SKILL_KEYS}
    project["writingSkillsUpdatedAt"] = at
    return at
