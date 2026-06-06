import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.gateway.feishu_client import feishu


async def main():
    open_id = settings.FEISHU_OPEN_ID
    if not open_id:
        print("FEISHU_OPEN_ID not configured in .env")
        return

    print(f"Sending to: {open_id}")
    await feishu.send_text(open_id, "ERP Agent test: message send OK")
    print("Sent successfully. Check Feishu.")


asyncio.run(main())
