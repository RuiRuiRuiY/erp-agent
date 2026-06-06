import json
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.gateway.feishu_client import feishu

logger = logging.getLogger(__name__)

app = FastAPI()

_graph = None


async def _get_graph():
    global _graph
    if _graph is None:
        from app.agent.graph import compile_graph_with_tools
        from app.agent.mcp_client import get_mcp_tools
        tools = await get_mcp_tools()
        _graph = compile_graph_with_tools(tools)
    return _graph


async def _process_message(open_id: str, text: str, message_id: str) -> None:
    try:
        await feishu.send_text(open_id, "正在处理...")
        g = await _get_graph()
        thread_id = str(uuid.uuid4())
        result = await g.ainvoke(
            {"messages": [HumanMessage(content=text)]},
            {"configurable": {"thread_id": thread_id}},
        )
        msgs = result.get("messages", [])
        reply = ""
        for m in reversed(msgs):
            c = getattr(m, "content", "")
            if isinstance(c, str) and c.strip():
                reply = c
                break
        if reply:
            await feishu.send_text(open_id, reply[:2000])
    except Exception:
        logger.exception("process_message failed")
        await feishu.send_text(open_id, "处理出错，请稍后重试")


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
