# customer_service/test/task/test_command_processor.py

"""
命令处理离线测试（不调真实 LLM）

覆盖 CommandProcessor 的四种命令 + TaskHandler 两阶段：
1. start_flow：新建 / 同流程不重复 / 打断新建 / 打断后恢复 / 空闲恢复 / 非法流程
2. set_slots：有任务才填 / 没任务不崩
3. cancel_flow：丢弃当前任务 + 取消过场 / 没有任务时静默
4. resume_flow：空闲指名 / 空闲取栈顶 / 打断当前再恢复 / 恢复失败回退
5. run 逐条应用：start_flow + set_slots 的顺序
6. TaskHandler：阶段1 改状态，空命令返回空列表
"""

import asyncio
from pathlib import Path

import pytest

from customer_service.domain.contexts import (
    CanceledSystemContext,
    InterruptedSystemContext,
    ResumedSystemContext,
    StartedSystemContext,
    TaskContext,
)
from customer_service.domain.state import DialogueState
from customer_service.task.action.builder import build_action_runner
from customer_service.task.command.models import (
    CancelFlowCommand,
    ResumeFlowCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from customer_service.task.command.processor import CommandProcessor
from customer_service.task.flow.executor import FlowExecutor
from customer_service.task.flow.loader import FlowLoader
from customer_service.task.handler import TaskHandler

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_flows():
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def _state() -> DialogueState:
    state = DialogueState(sender_id="u1")
    state.start_session()
    return state


def _processor() -> CommandProcessor:
    return CommandProcessor()


def _refund(slots: dict | None = None, step_id: str = "start") -> TaskContext:
    return TaskContext(flow_id="refund_request", step_id=step_id, slots=slots or {})


def _order_status(step_id: str = "start") -> TaskContext:
    return TaskContext(flow_id="order_status_query", step_id=step_id, slots={})


def _logistics(step_id: str = "start") -> TaskContext:
    return TaskContext(flow_id="logistics_tracking", step_id=step_id, slots={})


# ---------------- start_flow ----------------


def test_start_flow_creates_task_and_started_context():
    state = _state()
    processor = _processor()
    flows = _load_flows()

    processor.run(
        [StartFlowCommand(command="start_flow", flow="refund_request")],
        state,
        flows,
    )

    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.step_id == "start"
    assert state.paused_tasks == []

    system_context = state.active_system_task
    assert isinstance(system_context, StartedSystemContext)
    assert system_context.started_flow_id == "refund_request"
    assert system_context.started_flow_name == "退款申请"
    assert system_context.step_id == "start"


def test_start_flow_same_flow_does_not_restart():
    state = _state()
    state.start_active_task(_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason"))
    processor = _processor()

    processor.run(
        [StartFlowCommand(command="start_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    # 不重新开始，旧进度和槽位都保留
    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.step_id == "ask_refund_reason"
    assert state.active_task.slots == {"order_number": "A001"}
    assert state.paused_tasks == []


def test_start_flow_interrupts_current_task():
    state = _state()
    state.start_active_task(_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason"))
    processor = _processor()

    processor.run(
        [StartFlowCommand(command="start_flow", flow="logistics_tracking")],
        state,
        _load_flows(),
    )

    assert state.active_task.flow_id == "logistics_tracking"
    assert [task.flow_id for task in state.paused_tasks] == ["refund_request"]
    # 挂起保留旧进度
    assert state.paused_tasks[0].step_id == "ask_refund_reason"
    assert state.paused_tasks[0].slots == {"order_number": "A001"}

    system_context = state.active_system_task
    assert isinstance(system_context, InterruptedSystemContext)
    assert system_context.interrupted_flow_name == "退款申请"
    assert system_context.started_flow_name == "物流查询"


def test_start_flow_resumes_paused_task_when_interrupting():
    state = _state()
    state.start_active_task(_logistics())
    state.paused_tasks = [_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason")]
    processor = _processor()

    processor.run(
        [StartFlowCommand(command="start_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    # 目标在暂停栈 -> 恢复旧进度，物流被反过来挂起
    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.step_id == "ask_refund_reason"
    assert state.active_task.slots == {"order_number": "A001"}
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]

    system_context = state.active_system_task
    assert isinstance(system_context, InterruptedSystemContext)
    assert system_context.started_flow_id == "refund_request"


def test_start_flow_resumes_paused_task_when_idle():
    state = _state()
    state.paused_tasks = [_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason")]
    processor = _processor()

    processor.run(
        [StartFlowCommand(command="start_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.step_id == "ask_refund_reason"
    assert state.paused_tasks == []

    system_context = state.active_system_task
    assert isinstance(system_context, ResumedSystemContext)
    assert system_context.resumed_flow_name == "退款申请"


def test_start_flow_rejects_internal_system_flow():
    state = _state()
    with pytest.raises(ValueError, match="不能直接启动系统流程"):
        _processor().run(
            [StartFlowCommand(command="start_flow", flow="system_task_started")],
            state,
            _load_flows(),
        )


def test_start_flow_unknown_flow_raises():
    state = _state()
    with pytest.raises(ValueError, match="未知流程"):
        _processor().run(
            [StartFlowCommand(command="start_flow", flow="tuikuan_flow")],
            state,
            _load_flows(),
        )


# ---------------- set_slots ----------------


def test_set_slots_fills_active_task():
    state = _state()
    state.start_active_task(_refund())
    _processor().run(
        [SetSlotsCommand(command="set_slots", slots={"order_number": "A001", "refund_reason": "尺码不合适"})],
        state,
        _load_flows(),
    )

    assert state.active_task.slots == {"order_number": "A001", "refund_reason": "尺码不合适"}


def test_set_slots_without_active_task_is_noop():
    state = _state()
    _processor().run(
        [SetSlotsCommand(command="set_slots", slots={"order_number": "A001"})],
        state,
        _load_flows(),
    )

    assert state.active_task is None


# ---------------- cancel_flow ----------------


def test_cancel_flow_drops_task_and_activates_canceled_context():
    state = _state()
    state.start_active_task(_refund(slots={"order_number": "A001"}))
    _processor().run([CancelFlowCommand(command="cancel_flow")], state, _load_flows())

    assert state.active_task is None
    # 取消是丢弃，不进暂停栈
    assert state.paused_tasks == []

    system_context = state.active_system_task
    assert isinstance(system_context, CanceledSystemContext)
    assert system_context.canceled_flow_id == "refund_request"
    assert system_context.canceled_flow_name == "退款申请"


def test_cancel_flow_without_active_task_is_noop():
    state = _state()
    _processor().run([CancelFlowCommand(command="cancel_flow")], state, _load_flows())

    assert state.active_task is None
    assert state.active_system_task is None


# ---------------- resume_flow ----------------


def test_resume_flow_when_idle_with_explicit_flow():
    state = _state()
    state.paused_tasks = [_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason")]
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.slots == {"order_number": "A001"}
    assert state.paused_tasks == []

    system_context = state.active_system_task
    assert isinstance(system_context, ResumedSystemContext)
    assert system_context.resumed_flow_id == "refund_request"


def test_resume_flow_when_idle_without_flow_takes_stack_top():
    state = _state()
    state.paused_tasks = [_order_status(), _logistics()]
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow=None)],
        state,
        _load_flows(),
    )

    # LIFO：最近挂起的 logistics_tracking 先回来
    assert state.active_task.flow_id == "logistics_tracking"
    assert [task.flow_id for task in state.paused_tasks] == ["order_status_query"]


def test_resume_flow_interrupts_current_task():
    state = _state()
    state.start_active_task(_logistics())
    state.paused_tasks = [_refund(slots={"order_number": "A001"}, step_id="ask_refund_reason")]
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.slots == {"order_number": "A001"}
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]

    system_context = state.active_system_task
    assert isinstance(system_context, InterruptedSystemContext)
    assert system_context.interrupted_flow_name == "物流查询"
    assert system_context.started_flow_name == "退款申请"


def test_resume_flow_same_as_active_is_noop():
    state = _state()
    state.start_active_task(_refund(slots={"order_number": "A001"}))
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.slots == {"order_number": "A001"}
    assert state.paused_tasks == []


def test_resume_flow_failure_rolls_back_interrupt():
    state = _state()
    state.start_active_task(_order_status())
    state.paused_tasks = [_logistics()]
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow="refund_request")],
        state,
        _load_flows(),
    )

    # 目标不在暂停栈：把刚挂起的当前任务恢复回来，像什么都没发生
    assert state.active_task.flow_id == "order_status_query"
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]
    assert state.active_system_task is None


def test_resume_flow_with_empty_paused_stack_is_noop():
    state = _state()
    _processor().run(
        [ResumeFlowCommand(command="resume_flow", flow=None)],
        state,
        _load_flows(),
    )

    assert state.active_task is None


def test_resume_flow_unknown_flow_raises():
    state = _state()
    with pytest.raises(ValueError, match="未知流程"):
        _processor().run(
            [ResumeFlowCommand(command="resume_flow", flow="tuikuan_flow")],
            state,
            _load_flows(),
        )


# ---------------- run 逐条应用 ----------------


def test_run_applies_commands_in_order():
    state = _state()
    _processor().run(
        [
            StartFlowCommand(command="start_flow", flow="refund_request"),
            SetSlotsCommand(command="set_slots", slots={"order_number": "A001"}),
        ],
        state,
        _load_flows(),
    )

    # 先建任务，后填槽：顺序不能反
    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.slots == {"order_number": "A001"}


def test_multi_task_switching_lifecycle():
    """第8章的四步场景：开始 A -> 切到 B -> 填槽 -> 切回 A"""
    state = _state()
    processor = _processor()
    flows = _load_flows()

    processor.run([StartFlowCommand(command="start_flow", flow="order_status_query")], state, flows)
    assert state.active_task.flow_id == "order_status_query"
    assert state.paused_tasks == []

    processor.run([StartFlowCommand(command="start_flow", flow="logistics_tracking")], state, flows)
    assert state.active_task.flow_id == "logistics_tracking"
    assert [task.flow_id for task in state.paused_tasks] == ["order_status_query"]

    processor.run([SetSlotsCommand(command="set_slots", slots={"order_number": "A001"})], state, flows)
    assert state.active_task.slots == {"order_number": "A001"}

    processor.run([ResumeFlowCommand(command="resume_flow", flow="order_status_query")], state, flows)
    assert state.active_task.flow_id == "order_status_query"
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]


# ---------------- TaskHandler 两阶段 ----------------


def test_task_handler_phase_one_applies_commands():
    state = _state()
    handler = TaskHandler(
        flows=_load_flows(),
        command_processor=_processor(),
        action_runner=build_action_runner(),
        flow_executor=FlowExecutor(),
    )

    messages = asyncio.run(
        handler.handle(
            [StartFlowCommand(command="start_flow", flow="refund_request")],
            state,
        )
    )

    assert state.active_task.flow_id == "refund_request"
    # 阶段2真正推进流程：开始过场 + 缺槽追问
    assert [message.text for message in messages] == [
        "好的，我们先处理退款申请。",
        "请告诉我你的订单号。",
    ]
    assert state.active_task.step_id == "ask_order_number"


def test_task_handler_empty_commands_still_drives_flow():
    state = _state()
    state.start_active_task(_refund())
    handler = TaskHandler(
        flows=_load_flows(),
        command_processor=_processor(),
        action_runner=build_action_runner(),
        flow_executor=FlowExecutor(),
    )

    messages = asyncio.run(handler.handle([], state))

    # 空命令不改状态，但阶段2仍会推进当前流程并生成追问
    assert [message.text for message in messages] == ["请告诉我你的订单号。"]
    assert state.active_task.flow_id == "refund_request"
