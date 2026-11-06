# atguigu/test/task/verify_day09.py

"""
Day09 验证脚本（离线：不发真实 HTTP，不调真实 LLM）

八步验证 FlowExecutor：
1. 没有任务 -> action_listen，不产生消息
2. 新建退款 -> 开始过场 + 缺槽追问（context.response 引用生效）
3. 填订单号 -> 下一个 collect 追问
4. 填退款原因 -> 提交成功 + end 清空任务
5. 条件跳转：有 product_id 走推荐分支
6. 条件兜底：没有 product_id 追问商品
7. 打断 / 恢复 / 取消三种系统过场都能被消费
8. 聚焦对象自动补槽 + 业务任务跑到 end

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.task.verify_day09
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from atguigu.domain.messages import FocusedObject
from atguigu.domain.state import DialogueState
from atguigu.task.action.builder import build_action_runner
from atguigu.task.action.custom import shared
from atguigu.task.command.models import (
    CancelFlowCommand,
    ResumeFlowCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from atguigu.task.command.processor import CommandProcessor
from atguigu.task.flow.executor import FlowExecutor
from atguigu.task.flow.loader import FlowLoader
from atguigu.task.handler import TaskHandler

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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

    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

    async def get(self, url: str) -> _StubResponse:
        for keyword, payload in self.payloads.items():
            if keyword in url:
                return _StubResponse(payload)
        return _StubResponse({"data": None})


def _load_flows():
    return FlowLoader().load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def _handler(flows) -> TaskHandler:
    return TaskHandler(
        flows=flows,
        command_processor=CommandProcessor(),
        action_runner=build_action_runner(),
        flow_executor=FlowExecutor(),
    )


def _state() -> DialogueState:
    state = DialogueState(sender_id="day09_verify")
    state.start_session()
    return state


def _texts(messages) -> list[str]:
    return [message.text for message in messages]


def _show(state: DialogueState) -> None:
    active = state.active_task.flow_id if state.active_task else None
    active_step = state.active_task.step_id if state.active_task else None
    paused = [task.flow_id for task in state.paused_tasks]
    system = type(state.active_system_task).__name__ if state.active_system_task else None
    print(f"    active_task={active} (step={active_step})  paused={paused}  system={system}")


def _check_no_task(flows, executor: FlowExecutor) -> None:
    state = _state()
    messages = asyncio.run(executor.run_task(state, flows, build_action_runner()))
    action_call = executor.advance_until_action(state, flows)
    print(f"\n[1] 无任务：messages={messages}，action={action_call.action_name}")
    assert messages == []
    assert action_call.action_name == "action_listen"
    print("    ✅ 没有当前任务时只返回 action_listen，不产生消息")


def _check_refund_full_flow(flows) -> None:
    handler = _handler(flows)
    state = _state()

    messages = asyncio.run(handler.handle([StartFlowCommand(command="start_flow", flow="refund_request")], state))
    print(f"\n[2] 开始退款：{_texts(messages)}")
    assert _texts(messages) == ["好的，我们先处理退款申请。", "请告诉我你的订单号。"]
    assert state.active_task.step_id == "ask_order_number"
    assert state.active_system_task.step_id == "end"
    _show(state)

    messages = asyncio.run(
        handler.handle([SetSlotsCommand(command="set_slots", slots={"order_number": "A001"})], state)
    )
    print(f"[3] 填订单号：{_texts(messages)}")
    assert _texts(messages) == ["请简单说一下退款原因。"]
    assert state.active_task.step_id == "ask_refund_reason"

    messages = asyncio.run(
        handler.handle([SetSlotsCommand(command="set_slots", slots={"refund_reason": "尺码不合适"})], state)
    )
    print(f"[4] 填退款原因：{_texts(messages)}")
    assert _texts(messages) == ["好的，订单A001的退款申请已提交，原因是：尺码不合适。后续会尽快为你处理。"]
    assert state.active_task is None
    print("    ✅ 退款从 start 一路走到 end：过场、追问、填槽、回复、清任务")


def _check_conditional_branches(flows, client: _StubHttpClient) -> None:
    shared.http_client_module.http_client = client  # type: ignore[assignment]
    handler = _handler(flows)

    hit_state = _state()
    messages = asyncio.run(
        handler.handle(
            [
                StartFlowCommand(command="start_flow", flow="similar_product_recommendation"),
                SetSlotsCommand(command="set_slots", slots={"product_id": "P1001"}),
            ],
            hit_state,
        )
    )
    print(f"\n[5] 有 product_id：{_texts(messages)}")
    assert _texts(messages)[-1].startswith('我已经收到你对"春季风衣"的相似商品推荐需求')
    assert hit_state.active_task is None

    miss_state = _state()
    messages = asyncio.run(
        handler.handle([StartFlowCommand(command="start_flow", flow="similar_product_recommendation")], miss_state)
    )
    print(f"[6] 没有 product_id：{_texts(messages)}")
    assert _texts(messages)[-1] == "请先选择一个商品，再继续咨询。"
    assert miss_state.active_task.step_id == "ask_product_id"
    print("    ✅ 条件跳转命中推荐分支；缺槽时走兜底分支")


def _check_interrupt_resume_cancel(flows) -> None:
    handler = _handler(flows)
    state = _state()

    asyncio.run(handler.handle([StartFlowCommand(command="start_flow", flow="refund_request")], state))
    asyncio.run(handler.handle([SetSlotsCommand(command="set_slots", slots={"order_number": "A001"})], state))

    messages = asyncio.run(handler.handle([StartFlowCommand(command="start_flow", flow="logistics_tracking")], state))
    print(f"\n[7] 查物流打断退款：{_texts(messages)}")
    assert "好的，我们先把退款申请放一放，先处理物流查询。" in _texts(messages)
    assert [task.flow_id for task in state.paused_tasks] == ["refund_request"]

    messages = asyncio.run(handler.handle([ResumeFlowCommand(command="resume_flow", flow="refund_request")], state))
    print(f"    恢复退款：{_texts(messages)}")
    assert "好的，我们先把物流查询放一放，先处理退款申请。" in _texts(messages)
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]
    assert state.active_task.step_id == "ask_refund_reason"

    messages = asyncio.run(handler.handle([CancelFlowCommand(command="cancel_flow")], state))
    print(f"    取消退款：{_texts(messages)}")
    assert _texts(messages) == ["好的，退款申请先帮你取消。"]
    assert state.active_task is None
    print("    ✅ Interrupted / Resumed / Canceled 三种系统过场都被执行器消费")


def _check_focused_object(flows, client: _StubHttpClient) -> None:
    shared.http_client_module.http_client = client  # type: ignore[assignment]
    handler = _handler(flows)
    state = _state()
    state.set_focused_object(FocusedObject(id="O1001", type="order"))

    messages = asyncio.run(handler.handle([StartFlowCommand(command="start_flow", flow="logistics_tracking")], state))
    print(f"\n[8] 聚焦订单后查物流：{_texts(messages)}")
    assert _texts(messages) == [
        "好的，我们先处理物流查询。",
        "订单O1001由顺丰配送，物流单号是SF123456。当前进度：运输中。",
    ]
    assert state.active_task is None
    print("    ✅ focused_object 自动补槽，跳过订单号追问，任务一次跑完")


def main() -> None:
    flows = _load_flows()
    executor = FlowExecutor()
    client = _StubHttpClient(payloads={"/logistics": LOGISTICS_PAYLOAD, "/products/": PRODUCT_PAYLOAD})
    try:
        _check_no_task(flows, executor)
        _check_refund_full_flow(flows)
        _check_conditional_branches(flows, client)
        _check_interrupt_resume_cancel(flows)
        _check_focused_object(flows, client)
    finally:
        shared.http_client_module.http_client = None  # type: ignore[assignment]

    print("\nDay09 验证通过 ✅")


if __name__ == "__main__":
    main()
