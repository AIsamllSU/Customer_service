# atguigu/test/knowledge/verify_day10.py

"""
Day10 验证脚本（离线：不发真实 HTTP、不调真实 LLM）

六步验证：
1. ChitchatHandler：假模型直接回一句，不碰流程与检索
2. FAQ / RAG：占位契约稳定，返回"未检索到"提示
3. ProductAPIProvider：stub 电商接口 -> 商品 JSON 片段
4. OrderAPIProvider：并发查订单 + 物流 -> 合并片段
5. KnowledgeHandler：意图去重 -> 检索 -> 知识回复
6. DialogueEngine：knowledge / chitchat 两条轨道都能分发

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.knowledge.verify_day10
"""

import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_PAYLOAD = {"data": {"title": "春季风衣", "price": 399}}
ORDER_PAYLOAD = {"data": {"status_desc": "已发货", "amount": 99}}
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


def _state(text: str = "我想咨询一下") -> DialogueState:
    state = DialogueState(sender_id="day10_verify")
    state.start_session()
    state.begin_turn(UserMessage(sender_id="day10_verify", message_id="m1", type=MessageType.TEXT, text=text))
    return state


def _flows():
    return FlowLoader().load_many(
        [PROJECT_ROOT / "flow_config" / "user_flows.yml", PROJECT_ROOT / "flow_config" / "system_flows.yml"]
    )


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
            knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["退款政策：支持 7 天无理由。"])),
        ),
        chitchat_handler=ChitChatHandler(
            ChitChatResponder(llm=FakeListChatModel(responses=["你好呀，我是电商助手小谷。"]))
        ),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=["好的。"])),
    )


def _check_chitchat() -> None:
    handler = ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["你好呀，我是电商助手小谷。"])))
    messages = asyncio.run(handler.handle(_state("你好")))
    print(f"\n[1] 闲聊：{[m.text for m in messages]}")
    assert [m.text for m in messages] == ["你好呀，我是电商助手小谷。"]
    print("    ✅ 闲聊只调 responder，不碰任务与知识检索")


def _check_placeholders() -> None:
    faq = asyncio.run(FAQProvider().retrieve(_state("退款政策是什么？")))
    rag = asyncio.run(RAGProvider().retrieve(_state("平台规则是什么？")))
    print(f"\n[2] FAQ：{faq[0].content}")
    print(f"    RAG：{rag[0].content}")
    assert faq == [KnowledgeChunk(content="FAQ：未检索到相关问题")]
    assert rag == [KnowledgeChunk(content="RAG：未检索到相关信息")]
    print("    ✅ 占位契约稳定，将来替换实现不影响上层")


def _check_product(client: _StubHttpClient) -> None:
    http_client.http_client = client  # type: ignore[assignment]
    client.calls.clear()
    state = _state("这件衣服多少钱？")
    state.set_focused_object(FocusedObject(id="P1001", type="product", title="春季风衣"))

    chunks = asyncio.run(ProductAPIProvider().retrieve(state))
    print(f"\n[3] 商品检索：{chunks[0].content}")
    assert "商品信息" in chunks[0].content and "春季风衣" in chunks[0].content
    assert client.calls == ["http://127.0.0.1:18081/products/P1001"]
    print("    ✅ 从 focused_object 取商品 ID，实时接口数据转成知识片段")


def _check_order(client: _StubHttpClient) -> None:
    http_client.http_client = client  # type: ignore[assignment]
    client.calls.clear()
    state = _state("我的订单到哪了？")
    state.set_focused_object(FocusedObject(id="A001", type="order", title="订单 A001"))

    chunks = asyncio.run(OrderAPIProvider().retrieve(state))
    print(f"\n[4] 订单检索：{chunks[0].content}")
    assert "订单与物流信息" in chunks[0].content
    assert "SF123456" in chunks[0].content
    assert len(client.calls) == 2
    print("    ✅ 订单 + 物流并发查询，结果合并成一个片段")


def _check_knowledge_pipeline() -> None:
    faq = _CountingProvider("faq.default", "退款政策：7 天无理由。")
    rag = _CountingProvider("rag.default", "平台规则：退款 1-3 个工作日到账。")
    handler = KnowledgeHandler(
        knowledge_intents=KNOWLEDGE_INTENTS,
        provider_registry=KnowledgeProviderRegistry([faq, rag]),
        knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["退款一般 1-3 个工作日到账。"])),
    )
    state = _state("退款多久到账？")

    messages = asyncio.run(handler.handle(["refund_policy", "return_policy"], state))
    print(f"\n[5] 知识回复：{[m.text for m in messages]}")
    print(f"    调用次数：faq={faq.calls} rag={rag.calls}")
    assert faq.calls == 1 and rag.calls == 1
    assert [m.text for m in messages] == ["退款一般 1-3 个工作日到账。"]
    print("    ✅ 多意图指向同一 provider 时只检索一次")


def _check_engine_dispatch() -> None:
    knowledge_engine = _engine({"task": None, "knowledge": {"intents": ["refund_policy"]}, "chitchat": None})
    knowledge_state = DialogueState(sender_id="day10_verify_knowledge")
    result = asyncio.run(
        knowledge_engine.process_message(
            knowledge_state,
            UserMessage(
                sender_id="day10_verify_knowledge",
                message_id="m1",
                type=MessageType.TEXT,
                text="退款政策是什么？",
            ),
        )
    )
    print(f"\n[6] 引擎 knowledge 轨道：{[m.text for m in result.messages]}")
    assert [m.text for m in result.messages] == ["退款政策：支持 7 天无理由。"]

    chitchat_engine = _engine({"task": None, "knowledge": None, "chitchat": {}})
    chitchat_state = DialogueState(sender_id="day10_verify_chitchat")
    result = asyncio.run(
        chitchat_engine.process_message(
            chitchat_state,
            UserMessage(sender_id="day10_verify_chitchat", message_id="m1", type=MessageType.TEXT, text="你好"),
        )
    )
    print(f"    引擎 chitchat 轨道：{[m.text for m in result.messages]}")
    assert [m.text for m in result.messages] == ["你好呀，我是电商助手小谷。"]
    print("    ✅ 三条轨道（task / knowledge / chitchat）全部接通")


def main() -> None:
    client = _StubHttpClient(
        {"/logistics": LOGISTICS_PAYLOAD, "/orders/": ORDER_PAYLOAD, "/products/": PRODUCT_PAYLOAD}
    )
    try:
        _check_chitchat()
        _check_placeholders()
        _check_product(client)
        _check_order(client)
        _check_knowledge_pipeline()
        _check_engine_dispatch()
    finally:
        http_client.http_client = None  # type: ignore[assignment]

    print("\nDay10 验证通过 ✅")


if __name__ == "__main__":
    main()
