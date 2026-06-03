from httpx import AsyncClient, HTTPStatusError, RequestError, TimeoutException
from app.core.config import settings

_client: AsyncClient | None = None
_TIMEOUT_SECONDS = 30


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = AsyncClient(
            base_url=settings.ERP_BASE_URL,
            timeout=_TIMEOUT_SECONDS,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


class ErpConnectionError(Exception):
    def __init__(self, message: str, original: Exception | None = None):
        self.message = message
        self.original = original
        super().__init__(message)


class ErpApiError(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        self.error_code: str = body.get("error_code", "UNKNOWN")
        self.agent_suggestion: str | None = body.get("agent_suggestion")
        super().__init__(f"[{status_code}] {self.error_code}: {body.get('message', '')}")


async def _request(method: str, path: str, **kwargs) -> dict | list:
    client = await get_client()
    try:
        resp = await client.request(method, path, **kwargs)
    except TimeoutException as e:
        raise ErpConnectionError(f"请求超时 ({_TIMEOUT_SECONDS}s): {method} {path}", e)
    except RequestError as e:
        raise ErpConnectionError(f"网络错误: {method} {path} — {e}", e)

    try:
        data = resp.json()
    except Exception as e:
        raise ErpConnectionError(f"响应非合法 JSON: {resp.text[:200]}", e)

    if resp.is_error:
        raise ErpApiError(resp.status_code, data)

    return data


async def get(path: str, params: dict | None = None) -> dict | list:
    return await _request("GET", path, params=params)


async def post(path: str, json_body: dict) -> dict | list:
    return await _request("POST", path, json=json_body)
