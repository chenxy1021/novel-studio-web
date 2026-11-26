"""模型配置：base_url / model / 轻活模型。

存在本系统的数据目录（默认 <仓库>/data/gateway.json，跨书共用，不写进书稿目录——
书稿要能拷给别人，不该带着你的代理地址）。

默认指向本机 magpie 代理（OpenAI 兼容，无需 key）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.home import studio_home

DEFAULT_BASE_URL = os.environ.get("DSH_NOVEL_BASE_URL") or "http://127.0.0.1:3425/v1"
DEFAULT_MODEL = "workbuddy/deepseek-v4-pro"
DEFAULT_FAST_MODEL = "workbuddy/deepseek-v4.1-flash"


def settings_file() -> Path:
    override = os.environ.get("DSH_NOVEL_GATEWAY_FILE")
    if override:
        return Path(override)
    return studio_home() / "gateway.json"


def load_settings() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        raw = json.loads(settings_file().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = raw
    except (OSError, json.JSONDecodeError):
        pass
    return {
        "baseUrl": str(data.get("baseUrl") or DEFAULT_BASE_URL),
        "model": str(data.get("model") or DEFAULT_MODEL),
        "fastModel": str(data.get("fastModel") or DEFAULT_FAST_MODEL),
        "apiKeySet": bool(data.get("apiKey")),
        "savedAt": data.get("savedAt") or "",
    }


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    base_url = str(patch.get("baseUrl") or "").strip() or current["baseUrl"]
    if not base_url.startswith(("http://", "https://")):
        raise ValueError(f"baseUrl 必须以 http:// 或 https:// 开头：{base_url}")
    data: dict[str, Any] = {
        "baseUrl": base_url.rstrip("/"),
        "model": str(patch.get("model") or current["model"]).strip() or current["model"],
        "fastModel": str(patch.get("fastModel") or current["fastModel"]).strip() or current["fastModel"],
        "savedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if patch.get("apiKey"):
        data["apiKey"] = str(patch["apiKey"])
    elif current["apiKeySet"]:
        try:
            old = json.loads(settings_file().read_text(encoding="utf-8"))
            if isinstance(old, dict) and old.get("apiKey"):
                data["apiKey"] = old["apiKey"]
        except (OSError, json.JSONDecodeError):
            pass
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # 原子替换；半截文件会让下次读配置直接炸
    return load_settings()


def get_api_key() -> str:
    """读取保存的 key（不返回给设置页，只给写作调用内部用）。"""
    try:
        raw = json.loads(settings_file().read_text(encoding="utf-8"))
        return str(raw.get("apiKey") or "") if isinstance(raw, dict) else ""
    except (OSError, json.JSONDecodeError):
        return ""


def _request(url: str, *, key: str = "", timeout: float = 5.0) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:300]}
    except urllib.error.URLError as e:
        return 0, {"error": f"连不上 {url}：{e.reason}"}
    except (TimeoutError, OSError) as e:
        return 0, {"error": f"连不上 {url}：{e}"}


def ping_provider(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    """探活：GET {baseUrl}/models。返回 {ok, status, models:[id], baseUrl, error?}。"""
    cur = load_settings()
    base = str(((patch or {}).get("baseUrl") or cur["baseUrl"])).rstrip("/")
    key = str((patch or {}).get("apiKey") or "")
    if not key and cur["apiKeySet"]:
        try:
            key = json.loads(settings_file().read_text(encoding="utf-8")).get("apiKey") or ""
        except (OSError, json.JSONDecodeError):
            key = ""
    status, body = _request(f"{base}/models", key=key)
    rows = body.get("data") if isinstance(body, dict) else None
    models = [str(r.get("id")) for r in rows or [] if isinstance(r, dict) and r.get("id")]
    if status != 200:
        return {"ok": False, "status": status, "baseUrl": base, "models": [],
                "error": str((body or {}).get("error") or f"HTTP {status}")[:300]}
    return {"ok": True, "status": status, "baseUrl": base, "models": models, "error": ""}


def list_models() -> dict[str, Any]:
    return ping_provider()
