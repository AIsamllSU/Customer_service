# atguigu/test/api/verify_day10_api.py

"""
Day10 接口冒烟（真实 LLM，走完整 HTTP + Service + Engine 链路）

验证内容：
1. 闲聊：POST /api/chat "你好" -> chitchat 轨道 -> 非空回复
2. 知识：POST /api/chat "退款政策是什么？" -> knowledge 轨道 -> 非空回复
3. 状态落库：两位用户的 session 都被保存

运行（必须在 customer-service-backend 目录下，且百炼可用）：
    uv run python -m atguigu.test.api.verify_day10_api
"""

import asyncio
import sys
import uuid
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi.testclient import TestClient
from sqlalchemy import text

from atguigu.api.app import app
from atguigu.infrastructure import database


def _sender(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def main() -> None:
    chitchat_sender = _sender("day10_chitchat")
    knowledge_sender = _sender("day10_knowledge")

    with TestClient(app) as client:
        print("[1] 闲聊：你好")
        resp = client.post("/api/chat", json={"sender_id": chitchat_sender, "text": "你好"})
        print("    响应：", resp.json())
        assert resp.status_code == 200, resp.text
        assert resp.json()["messages"] and resp.json()["messages"][0]["text"]

        print("\n[2] 知识：退款政策是什么？")
        resp = client.post("/api/chat", json={"sender_id": knowledge_sender, "text": "退款政策是什么？"})
        print("    响应：", resp.json())
        assert resp.status_code == 200, resp.text
        assert resp.json()["messages"] and resp.json()["messages"][0]["text"]

    async def _read_states() -> None:
        database.init_db_engine()
        try:
            async with database.async_session() as session:
                for sender_id in (chitchat_sender, knowledge_sender):
                    state_json = (
                        await session.execute(
                            text("select state_json from dialogue_states where sender_id = :s"),
                            {"s": sender_id},
                        )
                    ).scalar_one_or_none()
                    assert state_json is not None
        finally:
            await database.close_db_engine()

    asyncio.run(_read_states())
    print("\nDay10 接口冒烟通过 ✅")


if __name__ == "__main__":
    main()
