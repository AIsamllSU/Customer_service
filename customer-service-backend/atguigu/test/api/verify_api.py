# atguigu/test/api/verify_api.py

"""
Day06 防幻觉校验 + 对象消息 验证脚本

验证内容：
1. POST /api/chat 文本消息（"我要退款"）-> 200，LLM 走 task 轨道并由 TaskHandler 接住
2. 同一用户发第二条消息 -> 200（验证 upsert 的更新分支 + 多轮历史）
3. 新用户直接点订单卡片（场景 B）-> 触发 OBJECT_REQUIRES_INTENT 澄清
4. 咨询"衣服材质"但没有聚焦商品 -> 缺对象，触发 MISSING_FOCUSED_OBJECT 澄清
5. GET /api/chat/history -> 结构正确
6. 数据库 dialogue_states 表里真的写入了三个用户的状态 JSON

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.api.verify_api
"""

import asyncio
import json
import sys
from pathlib import Path

# 支持两种运行方式：
#   1) uv run python -m atguigu.test.api.verify_api
#   2) uv run python atguigu/test/api/verify_api.py
# 直接运行脚本时 sys.path[0] 是脚本所在目录，找不到 atguigu 包，
# 这里手动把项目根（customer-service-backend）加进去。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi.testclient import TestClient
from sqlalchemy import text

from atguigu.api.app import app
from atguigu.infrastructure import database

SENDER_TEXT = "day06_verify_text"
SENDER_OBJECT = "day06_verify_object"
SENDER_KNOWLEDGE = "day06_verify_knowledge"


def _check_chat_flow(client: TestClient):
    print("\n[1] 文本消息 POST /api/chat（真实 LLM 决策）")
    resp = client.post("/api/chat", json={"sender_id": SENDER_TEXT, "text": "我要退款"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    print("    响应：", body)
    assert body["sender_id"] == SENDER_TEXT
    assert body["message_id"]
    # "我要退款" 应该被 LLM 判成 task 轨道；阶段2 推进退款流程并追问订单号
    assert len(body["messages"]) >= 1
    assert body["messages"][-1]["text"] == "请告诉我你的订单号。"

    print("\n[2] 同一用户发第二条消息（验证 upsert 更新分支 + 历史累积）")
    resp2 = client.post("/api/chat", json={"sender_id": SENDER_TEXT, "text": "订单号是 A001"})
    assert resp2.status_code == 200, resp2.text
    print("    响应：", resp2.json())
    assert resp2.json()["sender_id"] == SENDER_TEXT
    assert isinstance(resp2.json()["messages"], list)

    print("\n[3] 新用户直接点订单卡片（场景 B：没有流程，触发澄清）")
    resp3 = client.post(
        "/api/chat",
        json={
            "sender_id": SENDER_OBJECT,
            "object": {"type": "order", "id": "1001", "title": "测试订单"},
        },
    )
    assert resp3.status_code == 200, resp3.text
    body3 = resp3.json()
    print("    响应：", body3)
    assert body3["sender_id"] == SENDER_OBJECT
    assert body3["message_id"]  # 客户端没传，服务端用 uuid 生成
    # 场景 B → ClarifyResponder 澄清，必须有话
    assert len(body3["messages"]) == 1
    assert body3["messages"][0]["text"]

    print("\n[4] 咨询商品信息但没有聚焦商品（触发 MISSING_FOCUSED_OBJECT 澄清）")
    resp_k = client.post(
        "/api/chat",
        json={"sender_id": SENDER_KNOWLEDGE, "text": "这件衣服是什么材质的？"},
    )
    assert resp_k.status_code == 200, resp_k.text
    body_k = resp_k.json()
    print("    响应：", body_k)
    assert len(body_k["messages"]) == 1
    assert body_k["messages"][0]["text"]

    print("\n[5] GET /api/chat/history")
    resp4 = client.get("/api/chat/history", params={"sender_id": SENDER_TEXT})
    assert resp4.status_code == 200, resp4.text
    body4 = resp4.json()
    print("    响应：", body4)
    assert body4["sender_id"] == SENDER_TEXT
    assert [m["role"] for m in body4["messages"]] == ["user", "bot"]


async def _check_database():
    print("\n[6] 检查 dialogue_states 表")
    database.init_db_engine()
    try:
        async with database.async_session() as session:
            sql = text("select sender_id, state_json from dialogue_states where sender_id in (:a, :b, :c)")
            result = await session.execute(sql, {"a": SENDER_TEXT, "b": SENDER_OBJECT, "c": SENDER_KNOWLEDGE})
            rows = result.all()

        print(f"    查到 {len(rows)} 行")
        assert len(rows) == 3, f"期望 3 行，实际 {len(rows)} 行"

        for sender_id, state_json in rows:
            state = json.loads(state_json)
            print(f"    {sender_id}: {state_json[:120]}...")
            assert state["sender_id"] == sender_id
            assert isinstance(state["sessions"], list)
    finally:
        await database.close_db_engine()


def main():
    with TestClient(app) as client:
        _check_chat_flow(client)

    asyncio.run(_check_database())
    print("\n接口层验证全部通过 ✅")


if __name__ == "__main__":
    main()
