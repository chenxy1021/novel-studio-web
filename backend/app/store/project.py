"""project.json / bible.json / arbitrary JSON + text files (atomic writes)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .fsatomic import atomic_write
from .paths import LAYOUT, project_path


def read_json(file: str | os.PathLike, fallback: Any = ...) -> Any:
    try:
        return json.loads(Path(file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if fallback is not ...:
            return copy.deepcopy(fallback)
        raise
    except json.JSONDecodeError as e:
        raise ValueError(f"读取失败 {file}: {e}") from e


def write_json(file: str | os.PathLike, value: Any) -> Path:
    return atomic_write(file, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_text(file: str | os.PathLike) -> str:
    return Path(file).read_text(encoding="utf-8")


def write_text(file: str | os.PathLike, text: str) -> Path:
    return atomic_write(file, text)


def load_project(root: str | os.PathLike) -> dict[str, Any] | None:
    """None when the dir has no project.json (matches JS loadProject returning null)."""
    p = project_path(root, LAYOUT["project"])
    if not p.is_file():
        return None
    data = read_json(p)
    if not isinstance(data, dict):
        raise ValueError(f"project.json 不是对象：{p}")
    return data


def save_project(root: str | os.PathLike, project: dict[str, Any]) -> Path:
    return write_json(project_path(root, LAYOUT["project"]), project)


def load_bible(root: str | os.PathLike) -> dict[str, Any]:
    """Always returns the shape domain code expects, even for old books missing keys."""
    p = project_path(root, LAYOUT["bible"])
    data = read_json(p, None)
    base: dict[str, Any] = {
        "characters": [], "world": [], "rules": [], "style": {},
        "factions": [], "locations": [], "items": [], "relations": [], "infoGaps": [],
    }
    if isinstance(data, dict):
        base.update(data)
    return base


def save_bible(root: str | os.PathLike, bible: dict[str, Any]) -> Path:
    return write_json(project_path(root, LAYOUT["bible"]), bible)
