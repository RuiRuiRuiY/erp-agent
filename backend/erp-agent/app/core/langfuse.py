from langfuse import Langfuse

from app.core.config import settings

langfuse_client: Langfuse | None = None


def setup_langfuse() -> None:
    global langfuse_client
    if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
        langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
        )


def get_langfuse_callback():
    """获取 Langfuse CallbackHandler，未配置时返回 None。"""
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return None
    try:
        setup_langfuse()
        if not langfuse_client:
            return None
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception:
        return None


def make_langfuse_config(callback=None):
    """构建包含 Langfuse 回调的 config dict。"""
    if callback is None:
        callback = get_langfuse_callback()
    if callback is None:
        return {}
    return {"callbacks": [callback]}
