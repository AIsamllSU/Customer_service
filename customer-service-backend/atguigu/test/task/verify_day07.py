# atguigu/test/task/verify_day07.py

"""
Day07 验证脚本（离线，不调真实 LLM）

用假模型固定产出命令，观察 CommandProcessor 如何一步步改 DialogueState：
1. 我要退款       -> start_flow(refund_request)         新建 + Started
2. A001           -> set_slots(order_number)            填槽
3. 先帮我查物流   -> start_flow(logistics_tracking)     打断退款 + Interrupted
4. 继续刚才的退款 -> resume_flow(refund_request)        打断物流 + 恢复退款

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.task.verify_day07
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
from atguigu.domain.messages import MessageType, UserMessage
from atguigu.domain.state import DialogueState
from atguigu.engine.dialogue_engine import DialogueEngine
from atguigu.knowledge.handler import KnowledgeHandler
from atguigu.knowledge.intents import KNOWLEDGE_INTENTS
from atguigu.knowledge.providers import FAQProvider, OrderAPIProvider, ProductAPIProvider, RAGProvider
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

PLANS = [
    {
        "task": {"commands": [{"command": "start_flow", "flow": "refund_request"}]},
        "knowledge": None,
        "chitchat": None,
    },
    {
        "task": {"commands": [{"command": "set_slots", "slots": {"order_number": "A001"}}]},
        "knowledge": None,
        "chitchat": None,
    },
    {
        "task": {"commands": [{"command": "start_flow", "flow": "logistics_tracking"}]},
        "knowledge": None,
        "chitchat": None,
    },
    {
        "task": {"commands": [{"command": "resume_flow", "flow": "refund_request"}]},
        "knowledge": None,
        "chitchat": None,
    },
]

TEXTS = ["我要退款", "A001", "先帮我查物流", "继续刚才的退款"]


def _load_flows():
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def _show(state: DialogueState) -> None:
    active = state.active_task.flow_id if state.active_task else None
    active_step = state.active_task.step_id if state.active_task else None
    active_slots = dict(state.active_task.slots) if state.active_task else {}
    paused = [task.flow_id for task in state.paused_tasks]
    system = type(state.active_system_task).__name__ if state.active_system_task else None
    print(f"    active_task   = {active} (step={active_step}, slots={active_slots})")
    print(f"    paused_tasks  = {paused}")
    print(f"    system_task   = {system}")


def main():
    flows = _load_flows()
    planner = TurnPlanner(llm=FakeListChatModel(responses=[json.dumps(plan, ensure_ascii=False) for plan in PLANS]))
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
            knowledge_responder=KnowledgeResponder(llm=FakeListChatModel(responses=["知识回复"])),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder(llm=FakeListChatModel(responses=["闲聊回复"]))),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(llm=FakeListChatModel(responses=["好的。"])),
    )

    state = DialogueState(sender_id="day07_verify")
    for index, text in enumerate(TEXTS, start=1):
        print(f"[{index}] 用户：{text}")
        user_message = UserMessage(
            sender_id=state.sender_id,
            message_id=f"m{index}",
            type=MessageType.TEXT,
            text=text,
        )
        result = asyncio.run(engine.process_message(state, user_message))
        print(f"    回复：{[message.text for message in result.messages]}")
        _show(state)
        print()

    print("最终状态断言：")
    assert state.active_task.flow_id == "refund_request"
    assert state.active_task.slots["order_number"] == "A001"
    assert [task.flow_id for task in state.paused_tasks] == ["logistics_tracking"]
    print("    ✅ 退款任务带着 A001 从暂停栈回来，物流被挂起")

    print("\nDay07 验证通过 ✅")


if __name__ == "__main__":
    main()
