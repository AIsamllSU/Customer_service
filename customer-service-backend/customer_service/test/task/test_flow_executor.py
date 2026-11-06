# customer_service/test/task/test_flow_executor.py

"""
流程执行器离线测试（不调真实 LLM、不发真实 HTTP）

覆盖 FlowExecutor 的两层循环：
1. 无任务 -> action_listen
2. start / collect / action / end 四种 step 的推进
3. 系统过场（开始、补槽）与业务任务叠加执行
4. action step 先推进再返回（防死循环）
5. 条件跳转（有 / 无 product_id）
6. 聚焦对象自动补槽
7. action args 的 context.response 引用解析
8. 槽位写回、消息累积、业务任务结束后清空
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from customer_service.domain.contexts import CollectedSystemContext, TaskContext
from customer_service.domain.messages import BotMessage, FocusedObject
from customer_service.domain.state import DialogueState
from customer_service.task.action.base import Action, ActionResult
from customer_service.task.action.builder import build_action_runner
from customer_service.task.action.registry import ActionRegistry
from customer_service.task.action.runner import ActionRunner
from customer_service.task.flow.executor import FlowExecutor
from customer_service.task.flow.flows import Flow, FlowsList
from customer_service.task.flow.links import StaticLink
from customer_service.task.flow.loader import FlowLoader
from customer_service.task.flow.steps import ActionFlowStep, EndFlowStep, StartFlowStep

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR = FlowExecutor()


def _load_flows() -> FlowsList:
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


FLOWS = _load_flows()


def _state(flow_id: str | None = None, step_id: str = "start", slots: dict[str, Any] | None = None) -> DialogueState:
    state = DialogueState(sender_id="u_executor")
    state.start_session()
    if flow_id is not None:
        state.start_active_task(TaskContext(flow_id=flow_id, step_id=step_id, slots=slots or {}))
    return state


def _run(state: DialogueState) -> list[BotMessage]:
    return asyncio.run(EXECUTOR.run_task(state, FLOWS, build_action_runner()))


# ---------------- 无任务 ----------------------------


def test_no_active_task_returns_listen():
    state = _state()

    action_call = EXECUTOR.advance_until_action(state, FLOWS)

    assert action_call.action_name == "action_listen"
    assert asyncio.run(EXECUTOR.run_task(state, FLOWS, build_action_runner())) == []


# ---------------- 业务全流程 ----------------------------


def test_refund_flow_runs_from_start_to_end():
    # start 流程是 CommandProcessor 建的；这里直接从 start 步骤验证执行器
    state = _state("refund_request")

    messages = _run(state)
    assert [message.text for message in messages] == ["请告诉我你的订单号。"]
    assert state.active_task.step_id == "ask_order_number"
    # action_listen 之前 step 已推进到 end，下一轮由 end 清掉系统过场
    assert state.active_system_task.step_id == "end"

    state.set_slots({"order_number": "A001"})
    messages = _run(state)
    assert [message.text for message in messages] == ["请简单说一下退款原因。"]

    state.set_slots({"refund_reason": "尺码不合适"})
    messages = _run(state)
    assert [message.text for message in messages] == [
        "好的，订单A001的退款申请已提交，原因是：尺码不合适。后续会尽快为你处理。"
    ]
    assert state.active_task is None


def test_order_status_flow_writes_slots_back(monkeypatch):
    async def _fake_fetch(order_id):
        assert order_id == "A001"
        return {
            "status_desc": "已发货",
            "amount": 99,
            "items": [{"title_snapshot": "纯棉T恤"}],
        }

    monkeypatch.setattr("customer_service.task.action.custom.lookup_order_status.fetch_order", _fake_fetch)
    state = _state("order_status_query", slots={"order_number": "A001"})

    messages = _run(state)

    assert [message.text for message in messages] == ["订单A001当前状态是：已发货。订单金额 ¥99。商品：纯棉T恤。"]
    # 业务任务跑到 end，active_task 被清空
    assert state.active_task is None


# ---------------- action step 的顺序 ----------------------------


class _RecordingAction(Action):
    name = "action_record"

    def __init__(self, seen_step_ids: list[str | None]) -> None:
        self.seen_step_ids = seen_step_ids

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        self.seen_step_ids.append(state.active_task.step_id)
        return ActionResult(messages=[BotMessage(text="已记录")])


def _demo_flows() -> FlowsList:
    flow = Flow(
        id="demo_flow",
        steps=[
            StartFlowStep(id="start", next=[StaticLink(target="do")]),
            ActionFlowStep(id="do", action="action_record", next=[StaticLink(target="end")]),
            EndFlowStep(id="end", next=[]),
        ],
    )
    return FlowsList(flows=[flow])


def test_action_step_advances_step_id_before_running():
    seen: list[str | None] = []
    runner = ActionRunner(ActionRegistry())
    runner.registry.register(_RecordingAction(seen))
    state = _state("demo_flow")

    messages = asyncio.run(EXECUTOR.run_task(state, _demo_flows(), runner))

    # 执行 action 时 step_id 已经是下一个步骤（end），否则会死循环
    assert seen == ["end"]
    assert [message.text for message in messages] == ["已记录"]
    assert state.active_task is None


# ---------------- collect 与系统过场 ----------------------------


def test_collect_missing_slot_starts_system_flow(monkeypatch):
    state = _state("logistics_tracking")

    action_call = EXECUTOR.advance_until_action(state, FLOWS)

    assert action_call.action_name == "action_response"
    assert action_call.action_kwargs["text"] == "请告诉我你的订单号。"
    assert isinstance(state.active_system_task, CollectedSystemContext)
    assert state.active_system_task.slot_name == "order_number"
    # advance_until_action 返回 ActionCall 时，action step 已推进到下一个 listen
    assert state.active_system_task.step_id == "listen"


def test_system_flow_end_resumes_business_task(monkeypatch):
    async def _fake_fetch(order_id):
        return {"tracking_number": "SF123456", "logistics_company": "顺丰", "status_desc": "运输中"}

    monkeypatch.setattr("customer_service.task.action.custom.lookup_logistics.fetch_logistics", _fake_fetch)
    state = _state("logistics_tracking", step_id="ask_order_number")
    state.start_active_system_task(
        CollectedSystemContext(
            flow_id="system_collect_information",
            step_id="end",
            slot_name="order_number",
            response={"text": "请告诉我你的订单号。"},
        )
    )
    state.set_slots({"order_number": "A001"})

    messages = _run(state)

    assert [message.text for message in messages] == [
        "订单A001由顺丰配送，物流单号是SF123456。当前进度：运输中。",
    ]
    assert state.active_system_task is None
    assert state.active_task is None


def test_collect_autofills_from_focused_order(monkeypatch):
    async def _fake_fetch(order_id):
        assert order_id == "O1001"
        return {"tracking_number": "SF123456", "logistics_company": "顺丰", "status_desc": "运输中"}

    monkeypatch.setattr("customer_service.task.action.custom.lookup_logistics.fetch_logistics", _fake_fetch)
    state = _state("logistics_tracking")
    state.set_focused_object(FocusedObject(id="O1001", type="order"))

    messages = _run(state)

    assert "请告诉我你的订单号" not in [message.text for message in messages]
    assert messages[-1].text.startswith("订单O1001由顺丰配送")


def test_collect_autofills_from_focused_product(monkeypatch):
    async def _fake_fetch(product_id):
        assert product_id == "P1001"
        return {"title": "春季风衣"}

    monkeypatch.setattr("customer_service.task.action.custom.recommend_similar_products.fetch_product", _fake_fetch)
    state = _state("similar_product_recommendation")
    state.set_focused_object(FocusedObject(id="P1001", type="product"))

    messages = _run(state)

    assert messages[-1].text.startswith('我已经收到你对"春季风衣"的相似商品推荐需求')


# ---------------- 条件跳转 ----------------------------


def test_conditional_next_uses_product_slot(monkeypatch):
    async def _fake_fetch(product_id):
        assert product_id == "P1001"
        return {"title": "春季风衣"}

    monkeypatch.setattr("customer_service.task.action.custom.recommend_similar_products.fetch_product", _fake_fetch)
    state = _state("similar_product_recommendation", slots={"product_id": "P1001"})

    messages = _run(state)

    assert messages[-1].text.startswith('我已经收到你对"春季风衣"的相似商品推荐需求')
    assert state.active_task is None


def test_conditional_next_falls_back_without_product():
    state = _state("similar_product_recommendation")

    messages = _run(state)

    assert [message.text for message in messages] == ["请先选择一个商品，再继续咨询。"]
    assert state.active_task.step_id == "ask_product_id"


# ---------------- 异常边界 ----------------------------


def test_unknown_step_raises_value_error():
    state = _state("refund_request", step_id="missing_step")

    with pytest.raises(ValueError, match="不存在步骤"):
        EXECUTOR.advance_until_action(state, FLOWS)


def test_unsupported_action_args_reference_raises():
    step = ActionFlowStep(id="ask", action="action_response", args="slots.order_number")
    state = _state("refund_request", slots={"order_number": "A001"})

    with pytest.raises(ValueError, match="不支持的 action args 引用"):
        EXECUTOR._build_action_call(state, step)
