# atguigu/test/plan/test_validator_and_object.py

"""
Day06 离线测试（不调真实 LLM）

覆盖：
1. 轨道层校验：MISSING_TRACK / MULTIPLE_TRACKS
2. task 四重校验：空命令 / 非法命令 / 多 start_flow / 未知 flow
3. knowledge 校验：空意图 / 未知意图 / 缺聚焦对象 / 对象匹配
4. 对象消息三场景：能填槽 / 无流程澄清 / 在流程但槽不匹配
5. ClarifyResponder 规则兜底话术
"""

import asyncio
import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from atguigu.chitchat.handler import ChitChatHandler
from atguigu.chitchat.responder import ChitChatResponder
from atguigu.domain.contexts import TaskContext
from atguigu.domain.messages import FocusedObject, MessageType, UserMessage
from atguigu.domain.state import DialogueState
from atguigu.engine.dialogue_engine import DialogueEngine
from atguigu.knowledge.handler import KnowledgeHandler
from atguigu.knowledge.intents import KNOWLEDGE_INTENTS
from atguigu.knowledge.providers import FAQProvider, OrderAPIProvider, ProductAPIProvider, RAGProvider
from atguigu.knowledge.registry import KnowledgeProviderRegistry
from atguigu.knowledge.responder import KnowledgeResponder
from atguigu.plan.models import ClarifyReason, TaskTurnPlan, TurnPlan
from atguigu.plan.turn_planner import TurnPlanner
from atguigu.plan.turn_validator import TurnPlanValidator
from atguigu.responder.clarify_responder import ClarifyResponder
from atguigu.task.action.builder import build_action_runner
from atguigu.task.command.models import Command, SetSlotsCommand, StartFlowCommand
from atguigu.task.command.processor import CommandProcessor
from atguigu.task.flow.executor import FlowExecutor
from atguigu.task.flow.loader import FlowLoader
from atguigu.task.handler import TaskHandler

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLARIFY_REPLY = "好的，你想办理什么业务呢？"


def _load_flows():
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def _state(sender_id: str = "u1") -> DialogueState:
    state = DialogueState(sender_id=sender_id)
    state.start_session()
    return state


def _engine(plan: dict | None = None) -> DialogueEngine:
    if plan is None:
        plan = {"task": None, "knowledge": None, "chitchat": {}}
    return DialogueEngine(
        turn_planner=TurnPlanner(llm=FakeListChatModel(responses=[json.dumps(plan, ensure_ascii=False)])),
        task_handler=TaskHandler(
            flows=_load_flows(),
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
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=[CLARIFY_REPLY])),
    )


def _text_message(text: str, sender_id: str = "u1") -> UserMessage:
    return UserMessage(sender_id=sender_id, message_id="m1", type=MessageType.TEXT, text=text)


def _object_message(obj: FocusedObject, sender_id: str = "u1") -> UserMessage:
    return UserMessage(sender_id=sender_id, message_id="m1", type=MessageType.OBJECT, object=obj)


def _validate(turn_plan: TurnPlan, state: DialogueState | None = None):
    return TurnPlanValidator().validate(
        state=state or _state(),
        turn_plan=turn_plan,
        flow_list=_load_flows(),
        intents=KNOWLEDGE_INTENTS,
    )


# ---------------- 轨道层 ----------------


def test_missing_track():
    result = _validate(TurnPlan())
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_TRACK


def test_multiple_tracks():
    plan = TurnPlan.from_dict(
        {
            "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
            "knowledge": {"intents": ["refund_policy"]},
            "chitchat": None,
        }
    )
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.MULTIPLE_TRACKS


# ---------------- task 四重校验 ----------------


def test_task_commands_empty():
    result = _validate(TurnPlan(task=TaskTurnPlan(commands=[])))
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_TASK_COMMANDS


def test_task_command_type_invalid():
    # 不是四种已知子类之一
    result = _validate(TurnPlan(task=TaskTurnPlan(commands=[Command(command="unknown_command")])))
    assert result.valid is False
    assert result.reason is ClarifyReason.INVALID_TASK_COMMANDS


def test_task_multiple_start_flows():
    plan = TurnPlan(
        task=TaskTurnPlan(
            commands=[
                StartFlowCommand(command="start_flow", flow="refund_request"),
                StartFlowCommand(command="start_flow", flow="logistics_tracking"),
            ]
        )
    )
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.MULTIPLE_TASK_FLOWS


def test_task_unknown_flow_is_hallucination():
    plan = TurnPlan(
        task=TaskTurnPlan(
            commands=[
                StartFlowCommand(command="start_flow", flow="tuikuan_flow"),
            ]
        )
    )
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.UNKNOWN_TASK_FLOW


def test_task_valid():
    plan = TurnPlan(
        task=TaskTurnPlan(
            commands=[
                StartFlowCommand(command="start_flow", flow="refund_request"),
                SetSlotsCommand(command="set_slots", slots={"order_number": "A001"}),
            ]
        )
    )
    result = _validate(plan)
    assert result.valid is True
    assert result.reason is None


# ---------------- knowledge 校验 ----------------


def test_knowledge_empty_intents():
    plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": []}, "chitchat": None})
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT


def test_knowledge_unknown_intent():
    plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["made_up_intent"]}, "chitchat": None})
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT


def test_knowledge_requires_object_but_missing():
    plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["order_info"]}, "chitchat": None})
    result = _validate(plan)
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_FOCUSED_OBJECT


def test_knowledge_with_matching_object():
    state = _state()
    state.set_focused_object(FocusedObject(id="O1001", type="order", title="订单 O1001"))
    plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["order_info"]}, "chitchat": None})
    result = _validate(plan, state)
    assert result.valid is True


def test_knowledge_policy_needs_no_object():
    plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["refund_policy"]}, "chitchat": None})
    result = _validate(plan)
    assert result.valid is True


# ---------------- 对象消息三场景 ----------------


def test_scene_a_object_fills_unfilled_slot():
    state = _state()
    state.active_task = TaskContext(flow_id="refund_request", step_id="start", slots={})
    engine = _engine()

    commands = engine._resolve_object_commands(
        message=_object_message(FocusedObject(id="O1001", type="order")),
        state=state,
        flows=_load_flows(),
    )
    assert len(commands) == 1
    assert isinstance(commands[0], SetSlotsCommand)
    assert commands[0].slots == {"order_number": "O1001"}

    # 端到端：对象消息 -> 转命令 -> TaskHandler 阶段1 填槽，阶段2 推进到下一个 collect
    result = asyncio.run(engine.process_message(state, _object_message(FocusedObject(id="O1001", type="order"))))
    assert state.active_task.slots["order_number"] == "O1001"
    assert result.messages[-1].text == "请简单说一下退款原因。"


def test_scene_b_no_flow_triggers_clarify():
    state = _state()
    engine = _engine()

    result = asyncio.run(
        engine.process_message(state, _object_message(FocusedObject(id="O1001", type="order", title="订单 O1001")))
    )

    # 澄清走 ClarifyResponder（假模型返回固定话术）
    assert result.messages[0].text == CLARIFY_REPLY
    # 对象已经被记住
    assert state.focused_object.id == "O1001"


def test_scene_c_object_slot_mismatch_does_not_interrupt():
    state = _state()
    # 订单号已经填过，流程此刻在等退款原因
    state.active_task = TaskContext(
        flow_id="refund_request", step_id="ask_refund_reason", slots={"order_number": "A001"}
    )
    engine = _engine()

    commands = engine._resolve_object_commands(
        message=_object_message(FocusedObject(id="O1001", type="order")),
        state=state,
        flows=_load_flows(),
    )
    assert commands == []

    result = asyncio.run(engine.process_message(state, _object_message(FocusedObject(id="O1001", type="order"))))
    # 不打断：没有系统过场，只是按当前流程再追问一次退款原因
    assert [message.text for message in result.messages] == ["请简单说一下退款原因。"]
    assert state.active_system_task is not None
    assert state.active_system_task.flow_id == "system_collect_information"
    assert len(state.sessions[0].turns) == 1


def test_product_object_in_refund_flow_cannot_fill():
    state = _state()
    state.active_task = TaskContext(flow_id="refund_request", slots={})
    engine = _engine()

    commands = engine._resolve_object_commands(
        message=_object_message(FocusedObject(id="P2001", type="product")),
        state=state,
        flows=_load_flows(),
    )
    assert commands == []  # 退款流程只收 order_number / refund_reason


def test_object_message_engine_sets_focused_object():
    state = _state()
    engine = _engine()
    asyncio.run(
        engine.process_message(state, _object_message(FocusedObject(id="O1002", type="order", title="订单 O1002")))
    )
    assert state.focused_object == FocusedObject(id="O1002", type="order", title="订单 O1002")


# ---------------- ClarifyResponder 规则层 ----------------


def test_build_clarify_message_rules():
    responder = ClarifyResponder(llm=FakeListChatModel(responses=[CLARIFY_REPLY]))
    state = _state()
    state.set_focused_object(FocusedObject(id="O1001", type="order"))

    assert "订单" in responder.build_clarify_message(ClarifyReason.OBJECT_REQUIRES_INTENT, state)
    assert "业务" in responder.build_clarify_message(ClarifyReason.MISSING_TRACK, state)
    assert "商品信息、订单信息" in responder.build_clarify_message(ClarifyReason.MISSING_KNOWLEDGE_INTENT, state)
    # 内部细分原因走通用兜底
    assert "再确认一下" in responder.build_clarify_message(ClarifyReason.UNKNOWN_TASK_FLOW, state)


# ---------------- 文本校验失败 -> 澄清 ----------------


def test_engine_text_invalid_plan_triggers_clarify():
    state = _state()
    engine = _engine({"task": None, "knowledge": None, "chitchat": None})

    result = asyncio.run(engine.process_message(state, _text_message("随便说点什么")))

    assert result.messages[0].text == CLARIFY_REPLY
    assert len(state.sessions[0].turns) == 1
