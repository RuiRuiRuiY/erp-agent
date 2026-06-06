import json
import time

import httpx

from app.core.config import settings

_BASE = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self) -> None:
        self._app_id = settings.FEISHU_APP_ID
        self._app_secret = settings.FEISHU_APP_SECRET
        self._token: str = ""
        self._token_expires_at: float = 0
        self._http = httpx.AsyncClient(base_url=_BASE, timeout=15)

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = await self._http.post(
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        data = resp.raise_for_status().json()
        self._token = data["tenant_access_token"]
        self._token_expires_at = time.time() + data.get("expire", 7200)
        return self._token

    async def send_text(self, open_id: str, text: str) -> None:
        token = await self._ensure_token()
        resp = await self._http.post(
            "/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        resp.raise_for_status()

    async def send_card(self, open_id: str, card: dict) -> None:
        token = await self._ensure_token()
        resp = await self._http.post(
            "/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": open_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        resp.raise_for_status()


feishu = FeishuClient()
