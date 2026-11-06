# customer_service/test/api/test_chat_api.py

"""
接口测试（pytest 版）

运行：
    uv run pytest

覆盖内容：
1. 文本消息 / 对象消息正常返回
2. message_id 透传与服务端生成
3. 参数边界：缺 sender_id、text 与 object 都没传、history 缺 sender_id
4. 边界数据：Repository 读写往返 + 重复保存只保留一行（upsert）
"""

import asyncio
import json
import uuid

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import text

from customer_service.api.app import app
from customer_service.api.routers import dependencies
from customer_service.chitchat.handler import ChitChatHandler
from customer_service.chitchat.responder import ChitChatResponder
from customer_service.engine.dialogue_engine import DialogueEngine
from customer_service.infrastructure import database
from customer_service.knowledge.handler import KnowledgeHandler
from customer_service.knowledge.intents import KNOWLEDGE_INTENTS
from customer_service.knowledge.providers import FAQProvider, OrderAPIProvider, ProductAPIProvider, RAGProvider
from customer_service.knowledge.registry import KnowledgeProviderRegistry
from customer_service.knowledge.responder import KnowledgeResponder
from customer_service.plan.turn_planner import TurnPlanner
from customer_service.plan.turn_validator import TurnPlanValidator
from customer_service.repository.dialogue_state_repository import DialogueStateRepository
from customer_service.responder.clarify_responder import ClarifyResponder
from customer_service.task.action.builder import build_action_runner
from customer_service.task.command.processor import CommandProcessor
from customer_service.task.flow.executor import FlowExecutor
from customer_service.task.handler import TaskHandler


def _sender(prefix: str = "pytest") -> str:
    """每次用不同的用户 id，避免历史数据互相干扰。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_chat_text_message():
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"sender_id": _sender(), "text": "你好"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["messages"][0]["text"] == "我是智能客服小智"
    assert len(body["messages"]) == 2
    assert body["message_id"]


def test_chat_keeps_client_message_id():
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat",
            json={"sender_id": _sender(), "message_id": "fixed-id-1", "text": "你好"},
        )

    assert resp.status_code == 200
    assert resp.json()["message_id"] == "fixed-id-1"


def test_chat_object_message():
    with TestClient(app) as client:
        resp = client.post(
            "/api/chat",
            json={"sender_id": _sender(), "object": {"type": "order", "id": "1001"}},
        )

    assert resp.status_code == 200
    assert resp.json()["message_id"]  # 客户端没传，服务端生成


def test_chat_missing_sender_id_returns_422():
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"text": "你好"})

    assert resp.status_code == 422


def test_chat_without_text_and_object_returns_422():
    """边界：空消息不能进业务层，否则会被当成 OBJECT 类型继续往下走。"""
    with TestClient(app) as client:
        resp = client.post("/api/chat", json={"sender_id": _sender()})

    assert resp.status_code == 422


def test_history_structure():
    with TestClient(app) as client:
        resp = client.get("/api/chat/history", params={"sender_id": "u-history"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["sender_id"] == "u-history"
    assert [m["role"] for m in body["messages"]] == ["user", "bot"]


def test_history_missing_sender_id_returns_422():
    with TestClient(app) as client:
        resp = client.get("/api/chat/history")

    assert resp.status_code == 422


def test_repository_round_trip_and_upsert():
    """边界数据：新用户空状态 → 保存 → 重新读取 → 再保存仍只有一行。"""
    sender = _sender("pytest_repo")

    async def scenario():
        database.init_db_engine()
        try:
            async with database.async_session() as session:
                repo = DialogueStateRepository(session)

                # 新用户：应返回空状态，而不是报错
                state = await repo.load_state(sender)
                assert state.sender_id == sender
                assert state.sessions == []
                assert state.current_session_id is None

                # 改一点状态再保存，验证 JSON 能整份写入
                state.start_session()
                await repo.save_state(state)

                # 重新读取，验证 JSON 能整份还原
                loaded = await repo.load_state(sender)
                assert loaded.current_session_id is not None
                assert len(loaded.sessions) == 1

                # 再保存一次：走 upsert 更新分支，不应该多出一行
                await repo.save_state(loaded)
                count = (
                    await session.execute(
                        text("select count(*) from dialogue_states where sender_id = :s"),
                        {"s": sender},
                    )
                ).scalar_one()
                assert count == 1
        finally:
            await database.close_db_engine()

    asyncio.run(scenario())


def test_chat_task_flow_end_to_end_with_fake_llm():
    """
    端到端（不依赖真实 LLM）：

    HTTP 请求 -> 真引擎（假 LLM 固定出计划）-> TaskHandler/CommandProcessor
    -> Service 落库 -> 再查库确认槽位真的持久化了。

    这样即使外部 LLM 欠费 / 断网，也能验证整条业务链路。
    """
    sender = _sender("pytest_task")
    plans = [
        {
            "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
            "knowledge": None,
            "chitchat": None,
        },
        {
            "task": {"commands": [{"command": "set_slots", "slots": {"order_number": "A001"}}]},
            "knowledge": None,
            "chitchat": None,
        },
    ]
    engine = DialogueEngine(
        turn_planner=TurnPlanner(
            llm=FakeListChatModel(responses=[json.dumps(plan, ensure_ascii=False) for plan in plans])
        ),
        task_handler=TaskHandler(
            flows=dependencies.load_flows(),
            command_processor=CommandProcessor(),
            action_runner=build_action_runner(),
            flow_executor=FlowExecutor(),
        ),
        knowledge_handler=KnowledgeHandler(
            knowledge_intents=KNOWLEDGE_INTENTS,
            provider_registry=KnowledgeProviderRegistry(
                [ProductAPIProvider(), OrderAPIProvider(), FAQProvider(), RAGProvider()]
            ),
            knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["知识回复"])),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["闲聊回复"]))),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=["好的。"])),
    )
    app.dependency_overrides[dependencies.get_dialogue_engine] = lambda: engine
    try:
        with TestClient(app) as client:
            first = client.post("/api/chat", json={"sender_id": sender, "text": "我要退款"})
            second = client.post("/api/chat", json={"sender_id": sender, "text": "A001"})
    finally:
        app.dependency_overrides.pop(dependencies.get_dialogue_engine, None)

    assert first.status_code == 200
    assert second.status_code == 200

    async def read_persisted_state():
        database.init_db_engine()
        try:
            async with database.async_session() as session:
                repo = DialogueStateRepository(session)
                loaded = await repo.load_state(sender)
                assert loaded.active_task is not None
                assert loaded.active_task.flow_id == "refund_request"
                assert loaded.active_task.slots == {"order_number": "A001"}
        finally:
            await database.close_db_engine()

    asyncio.run(read_persisted_state())
