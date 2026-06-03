from httpx import AsyncClient

from app.core.config import settings

_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = AsyncClient(base_url=settings.ERP_BASE_URL)
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
