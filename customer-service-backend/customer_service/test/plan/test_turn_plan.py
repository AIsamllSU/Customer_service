# customer_service/test/plan/test_turn_plan.py

"""
计划解析离线测试（不调真实 LLM）

覆盖：
1. Command 四种命令的多态反序列化
2. TurnPlan 三个轨道 + 多轨道解析
3. HistoryBuilder 文本 / 对象渲染
4. 提示词 7 个字段构建与 jinja2 渲染
5. TurnPlanner 用假模型跑通"我要退款 -> start_flow"
6. DialogueEngine 整条链路（准备会话 -> 开 turn -> 计划 -> 分发 -> 提交）
"""

import asyncio
import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import PromptTemplate

from customer_service.chitchat.handler import ChitChatHandler
from customer_service.chitchat.responder import ChitChatResponder
from customer_service.domain.messages import BotMessage, FocusedObject, MessageType, UserMessage
from customer_service.domain.state import DialogueState, Turn
from customer_service.engine.dialogue_engine import DialogueEngine
from customer_service.knowledge.handler import KnowledgeHandler
from customer_service.knowledge.intents import KNOWLEDGE_INTENTS
from customer_service.knowledge.providers import FAQProvider, OrderAPIProvider, ProductAPIProvider, RAGProvider
from customer_service.knowledge.registry import KnowledgeProviderRegistry
from customer_service.knowledge.responder import KnowledgeResponder
from customer_service.plan.models import ChitchatTurnPlan, KnowledgeTurnPlan, TaskTurnPlan, TurnPlan
from customer_service.plan.turn_planner import TurnPlanner
from customer_service.plan.turn_validator import TurnPlanValidator
from customer_service.prompts.history_builder import HistoryBuilder
from customer_service.prompts.loader import load_prompt
from customer_service.responder.clarify_responder import ClarifyResponder
from customer_service.task.action.builder import build_action_runner
from customer_service.task.command.models import (
    CancelFlowCommand,
    Command,
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


def _fake_planner(plan: dict) -> TurnPlanner:
    """
    用假模型构造 TurnPlanner：模型永远返回同一段 JSON
    """
    fake_llm = FakeListChatModel(responses=[json.dumps(plan, ensure_ascii=False)])
    return TurnPlanner(llm=fake_llm)


def _engine(planner: TurnPlanner, chitchat_reply: str = "你好呀，我是电商助手小智。") -> DialogueEngine:
    """组装一个全离线的引擎：假模型 + 假澄清回复"""
    return DialogueEngine(
        turn_planner=planner,
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
            knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["这是知识回复。"])),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=[chitchat_reply]))),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=["好的，你想办理什么业务呢？"])),
    )


def _user(text: str, sender_id: str = "u1", message_id: str = "m1") -> UserMessage:
    return UserMessage(sender_id=sender_id, message_id=message_id, type=MessageType.TEXT, text=text)


def test_command_from_dict():
    assert isinstance(Command.from_dict({"command": "start_flow", "flow": "refund_request"}), StartFlowCommand)
    assert isinstance(Command.from_dict({"command": "set_slots", "slots": {"order_number": "A001"}}), SetSlotsCommand)
    assert isinstance(Command.from_dict({"command": "cancel_flow"}), CancelFlowCommand)

    resume = Command.from_dict({"command": "resume_flow", "flow": "refund_request"})
    assert isinstance(resume, ResumeFlowCommand)
    assert resume.flow == "refund_request"


def test_turn_plan_from_dict():
    task_plan = TurnPlan.from_dict(
        {
            "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
            "knowledge": None,
            "chitchat": None,
        }
    )
    assert isinstance(task_plan.task, TaskTurnPlan)
    assert isinstance(task_plan.task.commands[0], StartFlowCommand)
    assert task_plan.knowledge is None and task_plan.chitchat is None

    knowledge_plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["refund_policy"]}, "chitchat": None})
    assert isinstance(knowledge_plan.knowledge, KnowledgeTurnPlan)
    assert knowledge_plan.knowledge.intents == ["refund_policy"]

    # 注意：chitchat 是空对象 {}，要能解析成 ChitchatTurnPlan() 而不是 None
    chitchat_plan = TurnPlan.from_dict({"task": None, "knowledge": None, "chitchat": {}})
    assert isinstance(chitchat_plan.chitchat, ChitchatTurnPlan)

    # 多轨道
    multi_plan = TurnPlan.from_dict(
        {
            "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
            "knowledge": {"intents": ["refund_policy"]},
            "chitchat": None,
        }
    )
    assert multi_plan.task is not None and multi_plan.knowledge is not None


def test_history_builder_renders_text_and_object():
    text_turn = Turn(
        turn_id="t1",
        user_message=_user("我想查订单"),
        bot_messages=[BotMessage(text="请提供订单号"), BotMessage(text="好的")],
    )
    rendered = HistoryBuilder.build([text_turn])
    assert rendered == "USER: 我想查订单\nBOT: 请提供订单号\nBOT: 好的"

    object_turn = Turn(
        turn_id="t2",
        user_message=UserMessage(
            sender_id="u1",
            message_id="m2",
            type=MessageType.OBJECT,
            object=FocusedObject(id="A001", type="order", title="小米手机", attributes={"price": 1999}),
        ),
        bot_messages=[],
    )
    rendered = HistoryBuilder.build([object_turn])
    assert "订单对象" in rendered and "id=A001" in rendered and "price=1999" in rendered


def test_prompt_inputs_and_render():
    state = DialogueState(sender_id="u1")
    state.start_session()
    state.begin_turn(_user("我要退款"))

    inputs = _fake_planner({})._build_prompt_inputs(state, _load_flows())

    assert set(inputs) == {
        "user_message",
        "current_conversation",
        "active_task_json",
        "interrupted_tasks_json",
        "focused_object_json",
        "available_flows_json",
        "knowledge_intents_json",
    }
    assert inputs["user_message"] == "我要退款"
    # 给 LLM 的流程清单不带内部 steps
    assert "steps" not in inputs["available_flows_json"]
    assert "refund_request" in inputs["available_flows_json"]

    template = PromptTemplate.from_template(load_prompt("turn_plan"), template_format="jinja2")
    prompt_text = template.format(**inputs)
    assert '"我要退款"' in prompt_text
    assert "refund_request" in prompt_text


def test_turn_planner_predicts_start_flow():
    state = DialogueState(sender_id="u1")
    state.start_session()
    state.begin_turn(_user("我要退款"))

    planner = _fake_planner(
        {
            "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
            "knowledge": None,
            "chitchat": None,
        }
    )
    plan = asyncio.run(planner.predict(state, _load_flows()))

    assert plan.task is not None
    assert plan.task.commands[0].command == "start_flow"
    assert plan.task.commands[0].flow == "refund_request"


def test_engine_task_track_end_to_end():
    """整条链路：新用户 -> 准备会话 -> 开 turn -> LLM 计划 -> task 轨道入口 -> 提交"""
    engine = _engine(
        _fake_planner(
            {
                "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
                "knowledge": None,
                "chitchat": None,
            }
        )
    )
    state = DialogueState(sender_id="u1")

    result = asyncio.run(engine.process_message(state, _user("我要退款")))

    assert result.sender_id == "u1"
    # 两阶段中的阶段1已经落地：命令真正改到了 state
    assert state.active_task is not None
    assert state.active_task.flow_id == "refund_request"
    # 阶段2已接入 FlowExecutor：先播过场，再追问缺失槽位
    assert [message.text for message in result.messages] == [
        "好的，我们先处理退款申请。",
        "请告诉我你的订单号。",
    ]

    # 会话 / 轮次都落进了状态
    assert len(state.sessions) == 1
    assert len(state.sessions[0].turns) == 1
    assert state.sessions[0].turns[0].user_message.text == "我要退款"
    assert state.pending_turn is None


def test_engine_chitchat_track_returns_reply():
    """闲聊轨道：假模型返回固定问候，消息要能落到 turn 里"""
    engine = _engine(
        _fake_planner({"task": None, "knowledge": None, "chitchat": {}}),
        chitchat_reply="你好呀，我是电商助手小智。",
    )
    state = DialogueState(sender_id="u2")

    result = asyncio.run(engine.process_message(state, _user("你好", sender_id="u2")))

    assert [message.text for message in result.messages] == ["你好呀，我是电商助手小智。"]
    assert len(state.sessions[0].turns) == 1
