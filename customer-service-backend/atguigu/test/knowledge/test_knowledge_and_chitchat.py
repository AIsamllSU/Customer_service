# atguigu/test/knowledge/test_knowledge_and_chitchat.py

"""
Day10 离线测试（不调真实 LLM、不发真实 HTTP）

覆盖：
1. Provider 注册表与四个 provider
2. 商品 / 订单 API 检索（订单 + 物流并发）
3. FAQ / RAG 占位契约
4. KnowledgeHandler：意图去重、未知意图、拼接 chunks
5. ChitChatHandler / Responder：直接回复并写入上下文变量
6. DialogueEngine 两条轨道分发
"""

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from atguigu.chitchat.handler import ChitChatHandler
from atguigu.chitchat.responder import ChitChatResponder
from atguigu.domain.messages import FocusedObject, MessageType, UserMessage
from atguigu.domain.state import DialogueState
from atguigu.engine.dialogue_engine import DialogueEngine
from atguigu.infrastructure import http_client
from atguigu.knowledge.handler import KnowledgeHandler
from atguigu.knowledge.intents import KNOWLEDGE_INTENTS
from atguigu.knowledge.providers import (
    FAQProvider,
    KnowledgeChunk,
    KnowledgeProvider,
    OrderAPIProvider,
    ProductAPIProvider,
    RAGProvider,
)
from atguigu.knowledge.registry import KnowledgeProviderRegistry
from atguigu.knowledge.responder import KnowledgeResponder
from atguigu.plan.turn_planner import TurnPlanner
from atguigu.plan.turn_validator import TurnPlanValidator
from atguigu.responder.clarify_responder import ClarifyResponder
from atguigu.task.action.builder import build_action_runner
from atguigu.task.command.processor import CommandProcessor
from atguigu.task.flow.executor import FlowExecutor
from atguigu.task.flow.loader import FlowLoader
from atguigu.task.handler import TaskHandler

PRODUCT_PAYLOAD = {"data": {"title": "春季风衣", "price": 399}}
ORDER_PAYLOAD = {"data": {"status_desc": "已发货", "amount": 99, "items": [{"title_snapshot": "纯棉T恤"}]}}
LOGISTICS_PAYLOAD = {"data": {"tracking_number": "SF123456", "logistics_company": "顺丰", "status_desc": "运输中"}}


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubHttpClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(self, url):
        self.calls.append(url)
        for keyword, payload in self.payloads.items():
            if keyword in url:
                return _StubResponse(payload)
        return _StubResponse({"data": None})


class _CountingProvider(KnowledgeProvider):
    def __init__(self, provider_id: str, content: str) -> None:
        self.provider_id = provider_id
        self.content = content
        self.calls = 0

    async def retrieve(self, state):
        self.calls += 1
        return [KnowledgeChunk(content=self.content)]


def _state(user_text: str = "我想咨询一下") -> DialogueState:
    state = DialogueState(sender_id="u_day10")
    state.start_session()
    state.begin_turn(UserMessage(sender_id="u_day10", message_id="m1", type=MessageType.TEXT, text=user_text))
    return state


def _flows():
    root = Path(__file__).resolve().parents[3]
    return FlowLoader().load_many([root / "flow_config" / "user_flows.yml", root / "flow_config" / "system_flows.yml"])


# ---------------- Provider ----------------


def test_registry_get_and_unknown_id():
    registry = KnowledgeProviderRegistry([FAQProvider(), RAGProvider()])

    assert isinstance(registry.get("faq.default"), FAQProvider)
    with pytest.raises(KeyError):
        registry.get("api.product")


def test_faq_and_rag_are_contract_placeholders():
    faq_chunks = asyncio.run(FAQProvider().retrieve(_state()))
    rag_chunks = asyncio.run(RAGProvider().retrieve(_state()))

    assert faq_chunks == [KnowledgeChunk(content="FAQ：未检索到相关问题")]
    assert rag_chunks == [KnowledgeChunk(content="RAG：未检索到相关信息")]


def test_product_provider_retrieves_json(monkeypatch):
    stub = _StubHttpClient({"/products/": PRODUCT_PAYLOAD})
    monkeypatch.setattr(http_client, "http_client", stub)
    state = _state()
    state.set_focused_object(FocusedObject(id="P1001", type="product", title="春季风衣"))

    chunks = asyncio.run(ProductAPIProvider().retrieve(state))

    assert len(chunks) == 1
    assert "商品信息" in chunks[0].content
    assert "春季风衣" in chunks[0].content
    assert stub.calls == ["http://127.0.0.1:18081/products/P1001"]


def test_order_provider_fetches_order_and_logistics(monkeypatch):
    stub = _StubHttpClient({"/logistics": LOGISTICS_PAYLOAD, "/orders/": ORDER_PAYLOAD})
    monkeypatch.setattr(http_client, "http_client", stub)
    state = _state()
    state.set_focused_object(FocusedObject(id="A001", type="order", title="订单 A001"))

    chunks = asyncio.run(OrderAPIProvider().retrieve(state))

    assert len(chunks) == 1
    assert "订单与物流信息" in chunks[0].content
    assert "SF123456" in chunks[0].content
    # 订单与物流两个 URL 都被请求
    assert len(stub.calls) == 2
    assert any("/orders/A001/logistics" in url for url in stub.calls)


def test_product_provider_requires_focused_object():
    state = _state()

    with pytest.raises(ValueError, match="缺少聚焦商品"):
        asyncio.run(ProductAPIProvider().retrieve(state))


# ---------------- KnowledgeHandler ----------------


def test_knowledge_handler_dedupes_provider_and_responds():
    faq = _CountingProvider("faq.default", "退款政策：7 天无理由。")
    rag = _CountingProvider("rag.default", "平台规则：退款 1-3 个工作日到账。")
    handler = KnowledgeHandler(
        knowledge_intents=KNOWLEDGE_INTENTS,
        provider_registry=KnowledgeProviderRegistry([faq, rag]),
        knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["退款一般 1-3 个工作日到账。"])),
    )
    state = _state("退款多久到账？")

    messages = asyncio.run(handler.handle(["refund_policy", "return_policy"], state))

    # 两个意图都指向 faq/rag，每个 provider 只查一次
    assert faq.calls == 1 and rag.calls == 1
    assert [message.text for message in messages] == ["退款一般 1-3 个工作日到账。"]


def test_knowledge_handler_unknown_intent_raises():
    handler = KnowledgeHandler(
        knowledge_intents=KNOWLEDGE_INTENTS,
        provider_registry=KnowledgeProviderRegistry([FAQProvider()]),
        knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["不会用到"])),
    )

    with pytest.raises(KeyError):
        asyncio.run(handler.handle(["made_up_intent"], _state()))


# ---------------- Chitchat ----------------


def test_chitchat_handler_returns_reply():
    handler = ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["你好呀，我是电商助手小谷。"])))
    state = _state("你好")

    messages = asyncio.run(handler.handle(state))

    assert [message.text for message in messages] == ["你好呀，我是电商助手小谷。"]


def test_chitchat_handler_requires_pending_turn():
    handler = ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["你好"])))
    state = DialogueState(sender_id="u_empty")

    with pytest.raises(ValueError, match="没有待处理的用户消息"):
        asyncio.run(handler.handle(state))


# ---------------- Engine 分发 ----------------


def _engine(plan: dict) -> DialogueEngine:
    return DialogueEngine(
        turn_planner=TurnPlanner(llm=FakeListChatModel(responses=[json.dumps(plan, ensure_ascii=False)])),
        task_handler=TaskHandler(
            flows=_flows(),
            command_processor=CommandProcessor(),
            action_runner=build_action_runner(),
            flow_executor=FlowExecutor(),
        ),
        knowledge_handler=KnowledgeHandler(
            knowledge_intents=KNOWLEDGE_INTENTS,
            provider_registry=KnowledgeProviderRegistry([FAQProvider(), RAGProvider()]),
            knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["知识轨道回复"])),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["闲聊轨道回复"]))),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=["好的。"])),
    )


def test_engine_dispatches_knowledge_track():
    engine = _engine({"task": None, "knowledge": {"intents": ["refund_policy"]}, "chitchat": None})
    state = DialogueState(sender_id="u_knowledge")
    message = UserMessage(sender_id="u_knowledge", message_id="m1", type=MessageType.TEXT, text="退款政策是什么？")

    result = asyncio.run(engine.process_message(state, message))

    assert [bot.text for bot in result.messages] == ["知识轨道回复"]
    assert len(state.current_session().turns) == 1


def test_engine_dispatches_chitchat_track():
    engine = _engine({"task": None, "knowledge": None, "chitchat": {}})
    state = DialogueState(sender_id="u_chitchat")
    message = UserMessage(sender_id="u_chitchat", message_id="m1", type=MessageType.TEXT, text="你好")

    result = asyncio.run(engine.process_message(state, message))

    assert [bot.text for bot in result.messages] == ["闲聊轨道回复"]
    assert len(state.current_session().turns) == 1
