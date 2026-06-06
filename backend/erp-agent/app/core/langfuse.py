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
