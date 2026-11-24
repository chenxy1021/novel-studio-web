"""OpenAI 兼容 chat 调用：设置页配的 baseUrl / model / apiKey 在这里真正生效。

只用标准库（urllib），不引第三方 SDK。错误统一抛 LLMError，路由层转成 502，
前端据此告诉作者「模型没连上，旧稿没动」，而不是假装成功。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable

from .settings import get_api_key, load_settings


class LLMError(RuntimeError):
    """模型不可用、返回空内容或格式不对。调用方应把它当成「这次没做事」。"""


def _request(base: str, payload: dict[str, Any], *, accept: str) -> urllib.request.Request:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": accept},
    )
    key = get_api_key()
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    return req


def _post(base: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    req = _request(base, payload, accept="application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"模型返回 HTTP {e.code}：{detail}") from e
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
        raise LLMError(f"连不上模型服务 {base}：{e}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"模型返回的不是 JSON：{e}") from e


def _stream_post(
    base: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    on_delta: Callable[[str], None],
    on_reason: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """读 OpenAI 兼容的 `stream: true` SSE，边读边回调增量文本（和思考过程）。"""
    req = _request(base, payload, accept="text/event-stream")
    pieces: list[str] = []
    reason_pieces: list[str] = []
    model = str(payload.get("model") or "")
    usage: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                if chunk.get("model"):
                    model = str(chunk["model"])
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                if isinstance(delta, dict):
                    # DeepSeek/WorkBuddy 一类端点把思考过程放在 reasoning_content（有的叫 reasoning）。
                    reason = delta.get("reasoning_content")
                    if not isinstance(reason, str) or not reason:
                        reason = delta.get("reasoning")
                    if isinstance(reason, str) and reason:
                        reason_pieces.append(reason)
                        if on_reason:
                            on_reason(reason)
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        pieces.append(piece)
                        on_delta(piece)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise LLMError(f"模型返回 HTTP {e.code}：{detail}") from e
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
        raise LLMError(f"连不上模型服务 {base}：{e}") from e
    return {"text": "".join(pieces), "reason": "".join(reason_pieces), "model": model, "usage": usage}


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.6,
    max_tokens: int = 8000,
    timeout: float = 180.0,
    reasoning: str | None = "low",
    on_delta: Callable[[str], None] | None = None,
    on_reason: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """发一次 chat/completions，返回 {text, reason, model, usage}。

    reasoning 是 WorkBuddy/DeepSeek 一类模型的思考预算（none/low/high/max）。
    不传或服务端不认时自动退化成不带该字段的请求——普通 OpenAI 兼容端点也能用。
    不重试正文：改写有副作用，失败就是失败，避免同一章被改两遍。
    ``on_delta`` 打开流式：每收到一段增量文本就回调一次（前端用来边写边看）。
    ``on_reason`` 只收思考过程；只传它也会走流式，但正文不回调。
    """
    cfg = load_settings()
    base = str(cfg["baseUrl"]).rstrip("/")
    used_model = (model or str(cfg["model"])).strip()
    wants_stream = bool(on_delta or on_reason)
    payload: dict[str, Any] = {
        "model": used_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": wants_stream,
    }
    if reasoning:
        payload["reasoning"] = {"effort": reasoning}

    emitted = False

    def emit(piece: str) -> None:
        nonlocal emitted
        emitted = True
        if on_delta:
            on_delta(piece)

    try:
        if wants_stream:
            streamed = _stream_post(base, payload, timeout=timeout, on_delta=emit, on_reason=on_reason)
            if not streamed["text"].strip():
                raise LLMError("模型返回了空内容")
            return streamed
        body = _post(base, payload, timeout=timeout)
    except LLMError as e:
        # 有些 OpenAI 兼容端点会拒绝未知字段；去掉 reasoning 再试一次。
        # 已经吐出正文后不能重试，否则同一段会被写两遍。
        if reasoning and "HTTP 400" in str(e) and not emitted:
            payload.pop("reasoning", None)
            if wants_stream:
                return _stream_post(base, payload, timeout=timeout, on_delta=emit, on_reason=on_reason)
            body = _post(base, payload, timeout=timeout)
        else:
            raise

    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LLMError("模型没有返回 choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise LLMError("模型返回了空内容")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    reason = ""
    if isinstance(message, dict):
        raw_reason = message.get("reasoning_content") or message.get("reason")
        if isinstance(raw_reason, str):
            reason = raw_reason
    return {"text": text, "reason": reason, "model": used_model, "usage": usage}


def strip_fence(text: str) -> str:
    """模型偶尔把正文包进 ```markdown；正文里不会以三反引号开头，去掉即可。"""
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s
