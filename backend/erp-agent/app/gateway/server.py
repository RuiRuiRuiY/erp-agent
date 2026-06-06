import json
import logging

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from app.gateway.feishu_client import feishu

logger = logging.getLogger(__name__)

app = FastAPI()


async def _process_message(open_id: str, text: str, message_id: str) -> None:
    try:
        await feishu.send_text(open_id, "正在处理...")
        result = f"已收到消息: {text}"
        await feishu.send_text(open_id, result)
    except Exception:
        logger.exception("process_message failed")


@app.post("/")
async def feishu_webhook(request: Request, bg: BackgroundTasks) -> JSONResponse:
    body = await request.json()

    event_type = (
        body.get("header", {}).get("event_type")
        or body.get("type")
    )
    if event_type == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    if event_type == "im.message.receive_v1":
        event = body.get("event", {})
        sender = event.get("sender", {})
        message = event.get("message", {})
        open_id = sender.get("sender_id", {}).get("open_id", "")
        msg_type = message.get("msg_type", "")
        content_raw = message.get("content", "{}")
        message_id = message.get("message_id", "")

        if msg_type == "text":
            content = json.loads(content_raw)
            text = content.get("text", "")
            bg.add_task(_process_message, open_id, text, message_id)

    return JSONResponse({"code": 0, "msg": "ok"})
