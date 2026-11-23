"""novel-partner 桥：把工作室项目临时渲染成 novel-partner 的书目录，跑它的确定性检查。

移植自 novel-studio/lib/npartner.js。为什么还是「桥」而不是重写：
novel-partner 的检查（8 字复读、POV、套话、疑似别名、复读行）已有被 254 项回归锁住的实现，
在别处再写一遍必然漂移。这里只做：造临时书目录 → 调 np.py check --json → 映射成
{severity, code, message, hint} 契约。

边界：只取文本级检查（时间线/伏笔/角色退场由 domain 自己做，更准）；
任何失败（没装 np.py、超时、解析失败）都只产出 info，绝不抛。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

KEEP = {"empty-chapter", "repeat-ngram", "duplicate-line", "cliche", "pov-shift", "canon-alias"}
SEVERITY = {"error": "high", "warn": "mid", "info": "info"}
HINT = {
    "empty-chapter": "正文太短，先确认稿子贴全了",
    "repeat-ngram": "对照证据片段人工复核；≥5 次是硬伤，3–4 次先看是不是人名或成语",
    "duplicate-line": "相邻两行完全相同，多为粘贴重复",
    "cliche": "一级套话，按 novel-continuity 的改法换成具体动作",
    "pov-shift": "场景之间人称主导翻转，确认是否有意换视角",
    "canon-alias": "疑似未登记称呼；确认后把别名登进人物卡",
}
MAX_FINDINGS = 40
CONCURRENCY = 4
CHAPTER_TIMEOUT_S = 8
TOTAL_BUDGET_S = 30


def novel_partner_script() -> Path:
    return Path(os.environ.get("DSH_NOVEL_NP") or Path.home() / ".dsh" / "skills" / "novel-partner" / "scripts" / "np.py")


def _python_bin() -> str | None:
    for cand in (os.environ.get("DSH_NOVEL_PYTHON"), "python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"):
        if not cand:
            continue
        try:
            r = subprocess.run([cand, "-c", "import sys;print(sys.version_info[0])"],
                               capture_output=True, timeout=4, text=True)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "3":
            return cand
    return None


def _yaml_safe(v: Any) -> str:
    import re
    return re.sub(r"[\r\n]+", " ", str(v)).replace(":", "：").strip()


def _write_shadow(tmp: Path, chapters: list[dict[str, Any]], bible: dict[str, Any]) -> list[dict[str, Any]]:
    book_dir = tmp / "book"
    char_dir = tmp / "canon" / "characters"
    book_dir.mkdir(parents=True, exist_ok=True)
    char_dir.mkdir(parents=True, exist_ok=True)

    for c in (bible or {}).get("characters") or []:
        name = str((c or {}).get("name") or "").strip()
        if not name:
            continue
        raw_aliases = c.get("aliases")
        aliases = [_yaml_safe(a) for a in (raw_aliases if isinstance(raw_aliases, list) else [])]
        aliases = [a for a in aliases if a]
        safe = "".join("_" if ch in '\\/:*?"<>|' else ch for ch in name)
        lines = ["---", f"name: {_yaml_safe(name)}"]
        lines += (["aliases:", *(f"  - {a}" for a in aliases)] if aliases else ["aliases: []"])
        lines += ["---", ""]
        (char_dir / f"{safe}.md").write_text("\n".join(lines), encoding="utf-8")

    # 空台账：不带表头会让 novel-partner 报 threads-format，那是假问题
    (tmp / "canon" / "threads.md").write_text(
        "| ID | 描述 | 埋设章 | 预期回收章 | 状态 |\n|---|---|---|---|---|\n", encoding="utf-8"
    )

    files = []
    for c in chapters:
        no = str(int(c["number"])).zfill(3)
        file = book_dir / f"ch-{no}.md"
        title = _yaml_safe(c.get("title") or f"第{c['number']}章")
        body = str(c.get("text") or "").strip()
        file.write_text(f"---\nchapter: {int(c['number'])}\ntitle: {title}\n---\n{body}\n", encoding="utf-8")
        files.append({"number": int(c["number"]), "file": file})
    return files


def _map_one(number: int, finding: dict[str, Any]) -> dict[str, str] | None:
    raw = str((finding or {}).get("message") or "").strip()
    if not raw:
        return None
    import re
    tagged = raw if re.search(r"第\s*\d+\s*章", raw) else f"第{number}章 {raw}"
    return {
        "severity": SEVERITY.get(finding.get("level"), "info"),
        "code": f"np-{finding.get('check')}",
        "message": tagged,
        "hint": HINT.get(finding.get("check"), "来自 novel-partner 的确定性检查"),
    }


def novel_partner_findings(bible: dict[str, Any], chapters: list[dict[str, Any]]) -> list[dict[str, str]]:
    """跑 novel-partner 的文本级检查。返回工作室契约的 findings；永不抛异常。"""
    np_script = novel_partner_script()
    if not np_script.exists():
        return [{
            "severity": "info", "code": "np-unavailable",
            "message": "novel-partner 未安装，文本体检跳过（字数/复读/套话/POV/别名）",
            "hint": f"找不到 {np_script}；装到 ~/.dsh/skills/novel-partner，或用 DSH_NOVEL_NP 指定 np.py",
        }]
    py = _python_bin()
    if not py:
        return [{
            "severity": "info", "code": "np-unavailable",
            "message": "本机找不到 python3，novel-partner 文本体检跳过",
            "hint": "装 Python 3 或用 DSH_NOVEL_PYTHON 指定解释器",
        }]
    if not chapters:
        return []

    started = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="np-bridge-"))
    out: list[dict[str, str]] = []
    try:
        files = _write_shadow(tmp, chapters, bible)
        state = {"failed": 0, "skipped": 0}

        def worker(file: dict[str, Any]) -> list[dict[str, str]]:
            if time.monotonic() - started > TOTAL_BUDGET_S:
                state["skipped"] += 1
                return []
            try:
                r = subprocess.run([py, str(np_script), "check", str(file["file"]), "--json"],
                                   capture_output=True, timeout=CHAPTER_TIMEOUT_S, text=True,
                                   env={**os.environ})
            except (OSError, subprocess.SubprocessError):
                state["failed"] += 1
                return []
            if r.returncode != 0 or not r.stdout.strip():
                state["failed"] += 1
                return []
            try:
                payload = json.loads(r.stdout)
            except json.JSONDecodeError:
                state["failed"] += 1
                return []
            got = []
            for f in [*(payload.get("errors") or []), *(payload.get("warnings") or []), *(payload.get("info") or [])]:
                if f.get("check") not in KEEP:
                    continue
                mapped = _map_one(file["number"], f)
                if mapped:
                    got.append(mapped)
            return got

        with ThreadPoolExecutor(max_workers=min(CONCURRENCY, len(files))) as pool:
            for got in pool.map(worker, files):
                for f in got:
                    if len(out) >= MAX_FINDINGS:
                        break
                    out.append(f)

        if state["failed"]:
            out.append({
                "severity": "info", "code": "np-check-failed",
                "message": f"novel-partner 有 {state['failed']} 章没跑成（解释器报错或超时）",
                "hint": "单独跑一次 np.py check <章节文件> 看具体原因",
            })
        if state["skipped"]:
            out.append({
                "severity": "info", "code": "np-incomplete",
                "message": f"超过 {TOTAL_BUDGET_S} 秒预算，约 {state['skipped']} 章未做文本体检",
                "hint": "章节多时属正常；需要全量可单独跑 novel-partner",
            })
        if len(out) >= MAX_FINDINGS:
            out.append({
                "severity": "info", "code": "np-truncated",
                "message": f"novel-partner 的发现超过 {MAX_FINDINGS} 条，其余未列出",
                "hint": "这类问题通常是成片的复读或套话，先修前面的",
            })
    except Exception as err:  # noqa: BLE001 — 桥接失败不能让体检整体挂掉
        return [{
            "severity": "info", "code": "np-unavailable",
            "message": f"novel-partner 检查未运行：{err}",
            "hint": "体检其余部分不受影响；修好后再跑一次",
        }]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out
