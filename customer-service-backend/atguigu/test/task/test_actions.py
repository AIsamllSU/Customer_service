# atguigu/test/task/test_actions.py

"""
Day08 离线测试（不调真实 LLM、不发真实 HTTP）

覆盖：
1. ActionRegistry / ActionRunner 的注册、查找、分发
2. ActionListen 哨兵
3. ActionResponse 三模式：static 渲染、rephrase 润色、generate 生成、失败兜底、参数校验
4. 自定义 action：查订单 / 查物流 / 推荐商品（成功 + 降级）
5. shared：URL 拼接、剥壳、摘要拼接、HTTP 客户端未初始化 / 接口异常降级
6. builder：内置 + 自定义自动发现（含"只注册本模块定义的类"）
"""

import asyncio
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from atguigu.domain.constants import (
    ACTION_GENERATE_FALLBACK_TEXT,
    ACTION_LISTEN,
    ACTION_LOOKUP_LOGISTICS,
    ACTION_LOOKUP_ORDER_STATUS,
    ACTION_RECOMMEND_SIMILAR_PRODUCTS,
    ACTION_RESPONSE,
    SLOT_LOGISTICS_COMPANY,
    SLOT_LOGISTICS_STATUS,
    SLOT_ORDER_NUMBER,
    SLOT_ORDER_STATUS,
    SLOT_ORDER_SUMMARY,
    SLOT_PRODUCT_ID,
    SLOT_TRACKING_NUMBER,
)
from atguigu.domain.contexts import StartedSystemContext, TaskContext
from atguigu.domain.messages import MessageType, UserMessage
from atguigu.domain.state import DialogueState, Turn
from atguigu.task.action.base import Action, ActionResult
from atguigu.task.action.builder import build_action_runner
from atguigu.task.action.builtin.action_listen import ActionListen
from atguigu.task.action.builtin.action_response import ActionResponse
from atguigu.task.action.custom import shared
from atguigu.task.action.custom.lookup_logistics import LookupLogisticsAction
from atguigu.task.action.custom.lookup_order_status import LookupOrderStatusAction
from atguigu.task.action.custom.recommend_similar_products import RecommendSimilarProductsAction
from atguigu.task.action.errors import ActionConfigError, ActionError
from atguigu.task.action.registry import ActionRegistry
from atguigu.task.action.runner import ActionCall, ActionRunner


def _state(slots: dict[str, Any] | None = None, flow_id: str = "order_status_query") -> DialogueState:
    """构造带活跃业务任务的状态（并开启会话，便于 rephrase 读取历史）。"""
    state = DialogueState(sender_id="u_action")
    state.start_session()
    state.start_active_task(TaskContext(flow_id=flow_id, step_id="lookup", slots=slots or {}))
    state.pending_turn = Turn(
        turn_id="t1",
        user_message=UserMessage(sender_id="u_action", message_id="m1", type=MessageType.TEXT, text="查订单"),
        bot_messages=[],
    )
    return state


class _EchoAction(Action):
    """测试用动作：把 kwargs 原样放进槽位，证明 runner 真的把参数传下去了。"""

    name = "action_echo"

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        return ActionResult(slot_updates={"echo": action_kwargs.get("value")})


# ---------------- 注册表与执行器 ----------------


def test_registry_register_and_get():
    registry = ActionRegistry()
    action = _EchoAction()
    registry.register(action)

    assert registry.get("action_echo") is action
    assert registry.names() == ["action_echo"]


def test_registry_unknown_action_raises_keyerror():
    registry = ActionRegistry()
    with pytest.raises(KeyError, match="Unknown action"):
        registry.get("action_missing")


def test_runner_dispatches_kwargs_and_returns_result():
    runner = ActionRunner(ActionRegistry())
    runner.registry.register(_EchoAction())

    result = asyncio.run(runner.run(ActionCall(action_name="action_echo", action_kwargs={"value": 42}), _state()))

    assert result.slot_updates == {"echo": 42}


def test_action_call_defaults_to_empty_kwargs():
    call = ActionCall(action_name="action_listen")
    assert call.action_kwargs == {}


# ---------------- 内置 action ----------------


def test_action_listen_returns_empty_result():
    result = asyncio.run(ActionListen().run(_state(), {}))

    assert result.messages == []
    assert result.slot_updates == {}


def test_action_response_static_renders_slots():
    action = ActionResponse(llm=FakeListChatModel(responses=["不该被调用"]))
    state = _state(
        slots={
            SLOT_ORDER_NUMBER: "A001",
            SLOT_ORDER_STATUS: "已发货",
            SLOT_ORDER_SUMMARY: "订单金额 ¥99。",
        }
    )

    result = asyncio.run(
        action.run(
            state,
            {
                "mode": "static",
                "text": "订单{{ slots.order_number }}当前状态是：{{ slots.order_status }}。{{ slots.order_summary }}",
            },
        )
    )

    assert [message.text for message in result.messages] == ["订单A001当前状态是：已发货。订单金额 ¥99。"]


def test_action_response_static_uses_system_context():
    state = _state()
    state.start_active_system_task(
        StartedSystemContext(
            flow_id="system_task_started",
            step_id="start",
            started_flow_id="refund_request",
            started_flow_name="退款申请",
        )
    )

    result = asyncio.run(
        ActionResponse().run(state, {"mode": "static", "text": "好的，我们先处理{{ context.started_flow_name }}。"})
    )

    assert result.messages[0].text == "好的，我们先处理退款申请。"


def test_action_response_missing_text_raises_config_error():
    with pytest.raises(ActionConfigError, match="text"):
        asyncio.run(ActionResponse().run(_state(), {"mode": "static"}))


def test_action_response_unsupported_mode_raises_config_error():
    with pytest.raises(ActionConfigError, match="不支持"):
        asyncio.run(ActionResponse().run(_state(), {"mode": "rewrite", "text": "你好"}))


def test_action_response_rephrase_returns_llm_output():
    action = ActionResponse(llm=FakeListChatModel(responses=["亲，订单 A001 已经发货啦～"]))

    result = asyncio.run(
        action.run(
            _state(slots={SLOT_ORDER_NUMBER: "A001"}),
            {
                "mode": "rephrase",
                "text": "订单{{ slots.order_number }}已发货。",
                "prompt": "请改写建议回复：{current_response}",
            },
        )
    )

    assert result.messages[0].text == "亲，订单 A001 已经发货啦～"


def test_action_response_rephrase_falls_back_to_rendered_text(monkeypatch):
    action = ActionResponse(llm=FakeListChatModel(responses=["不会用到"]))

    async def _boom(self, prompt_text, state, rendered_text=""):
        raise ActionError("LLM down")

    monkeypatch.setattr(ActionResponse, "_call_llm", _boom)

    result = asyncio.run(
        action.run(
            _state(slots={SLOT_ORDER_NUMBER: "A001"}),
            {
                "mode": "rephrase",
                "text": "订单{{ slots.order_number }}已发货。",
                "prompt": "请改写建议回复：{current_response}",
            },
        )
    )

    assert result.messages[0].text == "订单A001已发货。"


def test_action_response_generate_returns_llm_output():
    action = ActionResponse(llm=FakeListChatModel(responses=["我来帮你查一下物流。"]))

    result = asyncio.run(action.run(_state(), {"mode": "generate", "prompt": "你是客服，请回复用户。"}))

    assert result.messages[0].text == "我来帮你查一下物流。"


def test_action_response_generate_falls_back_when_llm_fails(monkeypatch):
    action = ActionResponse(llm=FakeListChatModel(responses=["不会用到"]))

    async def _boom(self, prompt_text, state, rendered_text=""):
        raise ActionError("LLM down")

    monkeypatch.setattr(ActionResponse, "_call_llm", _boom)

    result = asyncio.run(action.run(_state(), {"mode": "generate", "prompt": "请生成回复"}))

    assert result.messages[0].text == ACTION_GENERATE_FALLBACK_TEXT


# ---------------- 自定义 action ----------------


def test_lookup_order_status_writes_slots(monkeypatch):
    async def _fake_fetch(order_id):
        assert order_id == "A001"
        return {
            "status_desc": "已发货",
            "amount": 99,
            "items": [{"title_snapshot": "纯棉T恤"}],
        }

    monkeypatch.setattr("atguigu.task.action.custom.lookup_order_status.fetch_order", _fake_fetch)

    result = asyncio.run(LookupOrderStatusAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))

    assert result.messages == []
    assert result.slot_updates == {
        SLOT_ORDER_STATUS: "已发货",
        SLOT_ORDER_SUMMARY: "订单金额 ¥99。商品：纯棉T恤。",
    }


def test_lookup_order_status_degrades_when_api_returns_none(monkeypatch):
    async def _fake_fetch(order_id):
        return None

    monkeypatch.setattr("atguigu.task.action.custom.lookup_order_status.fetch_order", _fake_fetch)

    result = asyncio.run(LookupOrderStatusAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))

    assert result.slot_updates[SLOT_ORDER_STATUS] == "查询失败"
    assert result.slot_updates[SLOT_ORDER_SUMMARY] == "暂时无法查到该订单信息，请稍后再试。"


def test_lookup_order_status_without_active_task_passes_none(monkeypatch):
    captured: list[str | None] = []

    async def _fake_fetch(order_id):
        captured.append(order_id)
        return None

    monkeypatch.setattr("atguigu.task.action.custom.lookup_order_status.fetch_order", _fake_fetch)

    state = DialogueState(sender_id="u_action")
    asyncio.run(LookupOrderStatusAction().run(state, {}))

    assert captured == [None]


def test_lookup_logistics_writes_slots(monkeypatch):
    async def _fake_fetch(order_id):
        return {"tracking_number": "SF123", "logistics_company": "顺丰", "status_desc": "运输中"}

    monkeypatch.setattr("atguigu.task.action.custom.lookup_logistics.fetch_logistics", _fake_fetch)

    result = asyncio.run(LookupLogisticsAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))

    assert result.slot_updates == {
        SLOT_TRACKING_NUMBER: "SF123",
        SLOT_LOGISTICS_COMPANY: "顺丰",
        SLOT_LOGISTICS_STATUS: "运输中",
    }


def test_lookup_logistics_degrades_when_api_returns_none(monkeypatch):
    async def _fake_fetch(order_id):
        return None

    monkeypatch.setattr("atguigu.task.action.custom.lookup_logistics.fetch_logistics", _fake_fetch)

    result = asyncio.run(LookupLogisticsAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))

    assert result.slot_updates == {
        SLOT_TRACKING_NUMBER: "未知",
        SLOT_LOGISTICS_COMPANY: "未知",
        SLOT_LOGISTICS_STATUS: "暂时无法查到物流信息，请稍后再试。",
    }


def test_recommend_similar_products_directly_returns_message(monkeypatch):
    async def _fake_fetch(product_id):
        assert product_id == "P1001"
        return {"title": "春季风衣"}

    monkeypatch.setattr("atguigu.task.action.custom.recommend_similar_products.fetch_product", _fake_fetch)

    result = asyncio.run(
        RecommendSimilarProductsAction().run(
            _state(
                slots={SLOT_PRODUCT_ID: "P1001"},
                flow_id="similar_product_recommendation",
            ),
            {},
        )
    )

    assert result.slot_updates == {}
    assert result.messages[0].text.startswith('我已经收到你对"春季风衣"的相似商品推荐需求')


def test_recommend_similar_products_falls_back_to_generic_label(monkeypatch):
    async def _fake_fetch(product_id):
        return None

    monkeypatch.setattr("atguigu.task.action.custom.recommend_similar_products.fetch_product", _fake_fetch)

    result = asyncio.run(RecommendSimilarProductsAction().run(_state(slots={}), {}))

    assert result.messages[0].text.startswith('我已经收到你对"这件商品"的相似商品推荐需求')


# ---------------- shared ----------------


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.raise_for_status_called = False

    def raise_for_status(self) -> None:
        self.raise_for_status_called = True

    def json(self) -> Any:
        return self._payload


class _StubClient:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.requested_urls: list[str] = []

    async def get(self, url: str) -> _StubResponse:
        self.requested_urls.append(url)
        if self._error is not None:
            raise self._error
        return _StubResponse(self._payload)


def test_extract_data_unwraps_data_field():
    assert shared._extract_data({"data": {"id": "1"}}) == {"id": "1"}
    assert shared._extract_data({"data": "oops"}) is None
    assert shared._extract_data(None) is None


def test_base_url_strips_trailing_slash():
    assert not shared._base_url().endswith("/")


def test_build_order_summary_uses_title_snapshot_and_amount():
    summary = shared._build_order_summary(
        {
            "amount": 199,
            "items": [
                {"title_snapshot": "羊毛衫"},
                {"title_snapshot": "牛仔裤"},
                {"title_snapshot": "第三件（不会出现）"},
            ],
        }
    )

    assert summary == "订单金额 ¥199。商品：羊毛衫、牛仔裤。"


def test_build_order_summary_returns_empty_string_without_data():
    assert shared._build_order_summary({}) == ""


def test_fetch_order_returns_none_when_http_client_not_initialized(monkeypatch):
    monkeypatch.setattr(shared.http_client_module, "http_client", None)

    assert asyncio.run(shared.fetch_order("A001")) is None


def test_fetch_order_returns_none_when_order_id_missing(monkeypatch):
    client = _StubClient(payload={"data": {"id": "A001"}})
    monkeypatch.setattr(shared.http_client_module, "http_client", client)

    assert asyncio.run(shared.fetch_order(None)) is None
    assert client.requested_urls == []


def test_fetch_order_success_unwraps_data(monkeypatch):
    client = _StubClient(payload={"data": {"status_desc": "已发货"}})
    monkeypatch.setattr(shared.http_client_module, "http_client", client)

    result = asyncio.run(shared.fetch_order("A001"))

    assert result == {"status_desc": "已发货"}
    assert client.requested_urls == [f"{shared._base_url()}/orders/A001"]


def test_fetch_order_url_encodes_special_characters(monkeypatch):
    client = _StubClient(payload={"data": {"id": "1"}})
    monkeypatch.setattr(shared.http_client_module, "http_client", client)

    asyncio.run(shared.fetch_order("A/001"))

    assert client.requested_urls == [f"{shared._base_url()}/orders/A%2F001"]


def test_fetch_order_degrades_when_request_raises(monkeypatch):
    client = _StubClient(error=RuntimeError("connection refused"))
    monkeypatch.setattr(shared.http_client_module, "http_client", client)

    assert asyncio.run(shared.fetch_order("A001")) is None


def test_fetch_logistics_and_product_paths(monkeypatch):
    client = _StubClient(payload={"data": {"ok": True}})
    monkeypatch.setattr(shared.http_client_module, "http_client", client)

    assert asyncio.run(shared.fetch_logistics("A001")) == {"ok": True}
    assert asyncio.run(shared.fetch_product("P1")) == {"ok": True}
    assert client.requested_urls == [
        f"{shared._base_url()}/orders/A001/logistics",
        f"{shared._base_url()}/products/P1",
    ]


# ---------------- builder 自动发现 ----------------


def test_build_action_runner_registers_builtin_and_custom_actions():
    runner = build_action_runner()

    assert runner.registry.names() == sorted(
        [
            ACTION_LISTEN,
            ACTION_RESPONSE,
            ACTION_LOOKUP_ORDER_STATUS,
            ACTION_LOOKUP_LOGISTICS,
            ACTION_RECOMMEND_SIMILAR_PRODUCTS,
        ]
    )
    assert isinstance(runner.registry.get(ACTION_RESPONSE), ActionResponse)
    assert isinstance(runner.registry.get(ACTION_RECOMMEND_SIMILAR_PRODUCTS), RecommendSimilarProductsAction)
