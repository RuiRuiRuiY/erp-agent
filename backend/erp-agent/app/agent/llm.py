"""LLM 实例缓存。

单进程 asyncio 模型下全局共享同一实例。多 Worker 部署时各进程独立副本。
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings

_llm_instance: Any = None


def _get_llm():
    """获取或创建缓存的 LLM 实例。"""
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    from langchain_openai import ChatOpenAI

    _llm_instance = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    return _llm_instance
