# atguigu/test/plan/verify_day06.py

"""
Day06 真实 LLM 验证脚本

验证：
1. 真实 LLM 计划 "我要退款" -> task 轨道，校验通过
2. 编造的 flow（tuikuan_flow）-> UNKNOWN_TASK_FLOW
3. "想了解商品材质"但没有聚焦商品 -> MISSING_FOCUSED_OBJECT -> 真实 LLM 润色澄清
4. 直接点订单卡片且没有流程 -> OBJECT_REQUIRES_INTENT 澄清

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.plan.verify_day06
"""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from atguigu.chitchat.handler import ChitChatHandler
from atguigu.chitchat.responder import ChitChatResponder
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
from atguigu.task.command.models import StartFlowCommand
from atguigu.task.command.processor import CommandProcessor
from atguigu.task.flow.executor import FlowExecutor
from atguigu.task.flow.loader import FlowLoader
from atguigu.task.handler import TaskHandler

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_flows():
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def _fresh_state(sender_id: str) -> DialogueState:
    state = DialogueState(sender_id=sender_id)
    state.start_session()
    return state


def main():
    flows = _load_flows()
    planner = TurnPlanner()
    validator = TurnPlanValidator()
    responder = ClarifyResponder()

    print("[1] 真实 LLM：我要退款")
    state = _fresh_state("day06_verify_llm")
    state.begin_turn(UserMessage(sender_id=state.sender_id, message_id="m1", type=MessageType.TEXT, text="我要退款"))
    plan = asyncio.run(planner.predict(state, flows))
    print("    TurnPlan：", plan)
    result = validator.validate(state, plan, flows, KNOWLEDGE_INTENTS)
    print("    校验结果：", result)
    assert result.valid is True

    print("\n[2] 防幻觉：编造的 flow")
    fake_plan = TurnPlan(
        task=TaskTurnPlan(
            commands=[
                StartFlowCommand(command="start_flow", flow="tuikuan_flow"),
            ]
        )
    )
    result = validator.validate(state, fake_plan, flows, KNOWLEDGE_INTENTS)
    print("    校验结果：", result)
    assert result.valid is False
    assert result.reason is ClarifyReason.UNKNOWN_TASK_FLOW

    print("\n[3] 需要对象的知识意图，但没有聚焦商品")
    knowledge_plan = TurnPlan.from_dict({"task": None, "knowledge": {"intents": ["product_info"]}, "chitchat": None})
    state2 = _fresh_state("day06_verify_object2")
    state2.begin_turn(
        UserMessage(sender_id=state2.sender_id, message_id="m2", type=MessageType.TEXT, text="这件衣服是什么材质的？")
    )
    result = validator.validate(state2, knowledge_plan, flows, KNOWLEDGE_INTENTS)
    print("    校验结果：", result)
    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_FOCUSED_OBJECT

    messages = asyncio.run(responder.respond(state=state2, reason=result.reason))
    print("    基础话术：", responder.build_clarify_message(result.reason, state2))
    print("    LLM 润色后：", messages[0].text)
    assert messages[0].text

    print("\n[4] 场景 B：没有流程时点订单卡片")
    engine = DialogueEngine(
        turn_planner=planner,
        task_handler=TaskHandler(
            flows=flows,
            command_processor=CommandProcessor(),
            action_runner=build_action_runner(),
            flow_executor=FlowExecutor(),
        ),
        knowledge_handler=KnowledgeHandler(
            knowledge_intents=KNOWLEDGE_INTENTS,
            provider_registry=KnowledgeProviderRegistry(
                [ProductAPIProvider(), OrderAPIProvider(), FAQProvider(), RAGProvider()]
            ),
            knowledge_responder=KnowledgeResponder(),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder()),
        turn_plan_validator=validator,
        clarify_responder=responder,
    )
    state3 = _fresh_state("day06_verify_object3")
    user_message = UserMessage(
        sender_id=state3.sender_id,
        message_id="m3",
        type=MessageType.OBJECT,
        object=FocusedObject(id="O1001", type="order", title="订单 O1001"),
    )
    result = asyncio.run(engine.process_message(state3, user_message))
    print("    focused_object：", state3.focused_object)
    print("    回复：", result.messages[0].text)
    assert state3.focused_object is not None
    assert result.messages[0].text

    print("\nDay06 真实 LLM 验证通过 ✅")


if __name__ == "__main__":
    main()
