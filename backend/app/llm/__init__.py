"""模型出口：把「用哪个 base_url / 哪个模型」收到一处，设置页与写作调用共用。"""

from .client import LLMError, chat, strip_fence
from .routing import reasoning_for
from .settings import (
    DEFAULT_BASE_URL,
    get_api_key,
    load_settings,
    list_models,
    ping_provider,
    save_settings,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "LLMError",
    "chat",
    "get_api_key",
    "load_settings",
    "list_models",
    "ping_provider",
    "reasoning_for",
    "save_settings",
    "strip_fence",
]
