# atguigu/test/task/verify_day08.py

"""
Day08 验证脚本（离线：不发真实 HTTP，不调真实 LLM）

六步验证：
1. builder 自动注册：5 个 action 全部就位
2. ActionListen：哨兵返回空结果
3. ActionResponse.static：slots 与 context 两种模板变量都能渲染
4. ActionResponse.rephrase / generate：假模型驱动；LLM 失败时兜底
5. 自定义 action：假电商接口返回成功 -> 写槽位
6. 自定义 action 降级：接口返回 None -> 写降级槽位，流程不崩

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.task.verify_day08
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from atguigu.domain.constants import (
    ACTION_GENERATE_FALLBACK_TEXT,
    ACTION_LISTEN,
    ACTION_RESPONSE,
    SLOT_LOGISTICS_COMPANY,
    SLOT_ORDER_NUMBER,
    SLOT_ORDER_STATUS,
    SLOT_ORDER_SUMMARY,
    SLOT_PRODUCT_ID,
    SLOT_TRACKING_NUMBER,
)
from atguigu.domain.contexts import StartedSystemContext, TaskContext
from atguigu.domain.state import DialogueState
from atguigu.task.action.builder import build_action_runner
from atguigu.task.action.builtin.action_response import ActionResponse
from atguigu.task.action.custom import shared
from atguigu.task.action.custom.lookup_logistics import LookupLogisticsAction
from atguigu.task.action.custom.lookup_order_status import LookupOrderStatusAction
from atguigu.task.action.custom.recommend_similar_products import RecommendSimilarProductsAction
from atguigu.task.action.errors import ActionError
from atguigu.task.action.runner import ActionCall, ActionRunner

ORDER_PAYLOAD = {
    "data": {
        "status_desc": "已发货",
        "amount": 99,
        "items": [{"title_snapshot": "纯棉T恤"}, {"title_snapshot": "休闲裤"}],
    }
}
LOGISTICS_PAYLOAD = {"data": {"tracking_number": "SF123456", "logistics_company": "顺丰", "status_desc": "运输中"}}
PRODUCT_PAYLOAD = {"data": {"title": "春季风衣"}}


class _StubResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _StubHttpClient:
    """按 URL 关键词返回固定数据，模拟电商中台。"""

    def __init__(self, payloads: dict[str, Any], fail: bool = False) -> None:
        self.payloads = payloads
        self.fail = fail
        self.requested_urls: list[str] = []

    async def get(self, url: str) -> _StubResponse:
        self.requested_urls.append(url)
        if self.fail:
            raise RuntimeError("模拟电商接口故障")
        for keyword, payload in self.payloads.items():
            if keyword in url:
                return _StubResponse(payload)
        return _StubResponse({"data": None})


def _state(slots: dict[str, Any] | None = None, flow_id: str = "order_status_query") -> DialogueState:
    state = DialogueState(sender_id="day08_verify")
    state.start_session()
    state.start_active_task(TaskContext(flow_id=flow_id, step_id="start", slots=slots or {}))
    return state


def _check_registry(runner: ActionRunner) -> None:
    names = runner.registry.names()
    print(f"\n[1] Action 注册表：{names}")
    assert names == sorted(
        [
            ACTION_RESPONSE,
            ACTION_LISTEN,
            "action_lookup_order_status",
            "action_lookup_logistics",
            "action_recommend_similar_products",
        ]
    )
    print("    ✅ 内置 2 个 + 自定义 3 个，全部自动装配")


def _check_listen(runner: ActionRunner) -> None:
    result = asyncio.run(runner.run(ActionCall(action_name=ACTION_LISTEN), _state()))
    print(f"\n[2] ActionListen -> messages={result.messages}, slot_updates={result.slot_updates}")
    assert result.messages == [] and result.slot_updates == {}
    print("    ✅ 哨兵不产生任何内容，只作为'等用户输入'的信号")


def _check_static(runner: ActionRunner) -> None:
    state = _state(
        slots={
            SLOT_ORDER_NUMBER: "A001",
            SLOT_ORDER_STATUS: "已发货",
            SLOT_ORDER_SUMMARY: "订单金额 ¥99。商品：纯棉T恤。",
        }
    )
    result = asyncio.run(
        runner.run(
            ActionCall(
                action_name=ACTION_RESPONSE,
                action_kwargs={
                    "text": (
                        "订单{{ slots.order_number }}当前状态是：{{ slots.order_status }}。{{ slots.order_summary }}"
                    )
                },
            ),
            state,
        )
    )
    print(f"\n[3] static 渲染：{result.messages[0].text}")
    assert result.messages[0].text == "订单A001当前状态是：已发货。订单金额 ¥99。商品：纯棉T恤。"

    system_state = _state()
    system_state.start_active_system_task(
        StartedSystemContext(
            flow_id="system_task_started",
            started_flow_id="refund_request",
            started_flow_name="退款申请",
        )
    )
    system_result = asyncio.run(
        runner.run(
            ActionCall(
                action_name=ACTION_RESPONSE,
                action_kwargs={"text": "好的，我们先处理{{ context.started_flow_name }}。"},
            ),
            system_state,
        )
    )
    print(f"    系统过场 context 渲染：{system_result.messages[0].text}")
    assert system_result.messages[0].text == "好的，我们先处理退款申请。"
    print("    ✅ slots / context 两套模板变量都正确")


def _check_llm_modes() -> None:
    fake = FakeListChatModel(responses=["亲，订单 A001 已经发货啦～"])
    rephrase = asyncio.run(
        ActionResponse(llm=fake).run(
            _state(slots={SLOT_ORDER_NUMBER: "A001"}),
            {
                "mode": "rephrase",
                "text": "订单{{ slots.order_number }}已发货。",
                "prompt": "请改写建议回复：{current_response}",
            },
        )
    )
    print(f"\n[4] rephrase：{rephrase.messages[0].text}")
    assert rephrase.messages[0].text == "亲，订单 A001 已经发货啦～"

    fake_generate = FakeListChatModel(responses=["我来帮你查一下物流进度。"])
    generated = asyncio.run(
        ActionResponse(llm=fake_generate).run(
            _state(),
            {"mode": "generate", "prompt": "你是电商客服，请生成一句回复。"},
        )
    )
    print(f"    generate：{generated.messages[0].text}")
    assert generated.messages[0].text == "我来帮你查一下物流进度。"

    failing = ActionResponse(llm=FakeListChatModel(responses=["不会用到"]))

    async def _boom(self, prompt_text, state, rendered_text=""):
        raise ActionError("模拟 LLM 欠费")

    failing._call_llm = _boom.__get__(failing)  # type: ignore[method-assign]

    fallback_rephrase = asyncio.run(
        failing.run(
            _state(slots={SLOT_ORDER_NUMBER: "A001"}),
            {
                "mode": "rephrase",
                "text": "订单{{ slots.order_number }}已发货。",
                "prompt": "请改写：{current_response}",
            },
        )
    )
    print(f"    rephrase 失败兜底：{fallback_rephrase.messages[0].text}")
    assert fallback_rephrase.messages[0].text == "订单A001已发货。"

    fallback_generate = asyncio.run(failing.run(_state(), {"mode": "generate", "prompt": "请生成回复"}))
    print(f"    generate 失败兜底：{fallback_generate.messages[0].text}")
    assert fallback_generate.messages[0].text == ACTION_GENERATE_FALLBACK_TEXT
    print("    ✅ 三模式可用；LLM 故障时 rephrase 回底稿、generate 给兜底话术")


def _check_custom_actions(client: _StubHttpClient) -> None:
    shared.http_client_module.http_client = client  # type: ignore[assignment]

    order_result = asyncio.run(LookupOrderStatusAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))
    print(f"\n[5] 查订单：{order_result.slot_updates}")
    assert order_result.slot_updates[SLOT_ORDER_STATUS] == "已发货"
    assert order_result.slot_updates[SLOT_ORDER_SUMMARY] == "订单金额 ¥99。商品：纯棉T恤、休闲裤。"

    logistics_result = asyncio.run(LookupLogisticsAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))
    print(f"    查物流：{logistics_result.slot_updates}")
    assert logistics_result.slot_updates[SLOT_TRACKING_NUMBER] == "SF123456"
    assert logistics_result.slot_updates[SLOT_LOGISTICS_COMPANY] == "顺丰"

    recommend_result = asyncio.run(
        RecommendSimilarProductsAction().run(
            _state(slots={SLOT_PRODUCT_ID: "P1001"}, flow_id="similar_product_recommendation"),
            {},
        )
    )
    print(f"    推荐商品：{recommend_result.messages[0].text}")
    assert "春季风衣" in recommend_result.messages[0].text
    print(f"    实际请求：{client.requested_urls}")
    print("    ✅ 查询类写槽位、推荐类直接发消息，分工符合设计")


def _check_degradation() -> None:
    failing_client = _StubHttpClient(payloads={}, fail=True)
    shared.http_client_module.http_client = failing_client  # type: ignore[assignment]

    order_result = asyncio.run(LookupOrderStatusAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))
    logistics_result = asyncio.run(LookupLogisticsAction().run(_state(slots={SLOT_ORDER_NUMBER: "A001"}), {}))
    print(f"\n[6] 接口故障时的查订单：{order_result.slot_updates}")
    print(f"    接口故障时的查物流：{logistics_result.slot_updates}")
    assert order_result.slot_updates[SLOT_ORDER_STATUS] == "查询失败"
    assert logistics_result.slot_updates[SLOT_TRACKING_NUMBER] == "未知"
    print("    ✅ 异常不外抛，降级槽位保证流程继续")

    shared.http_client_module.http_client = None  # type: ignore[assignment]
    not_initialized = asyncio.run(shared.fetch_order("A001"))
    assert not_initialized is None
    print("    ✅ 客户端未初始化也不崩，返回 None 交给上层兜底")


def main() -> None:
    runner = build_action_runner()
    _check_registry(runner)
    _check_listen(runner)
    _check_static(runner)
    _check_llm_modes()

    client = _StubHttpClient(
        payloads={
            "/logistics": LOGISTICS_PAYLOAD,
            "/orders/": ORDER_PAYLOAD,
            "/products/": PRODUCT_PAYLOAD,
        }
    )
    _check_custom_actions(client)
    _check_degradation()

    print("\nDay08 验证通过 ✅")


if __name__ == "__main__":
    main()
