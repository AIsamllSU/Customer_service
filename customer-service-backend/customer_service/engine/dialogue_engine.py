# customer_service/engine/dialogue_engine.py

"""
对话引擎（三轨决策 + 防幻觉校验 + 对象消息）

引擎自己做三件事：理解、决策、执行。
- 文本消息：LLM 出计划 -> 防幻觉校验 -> 按轨道分发
- 对象消息：能填槽就填槽，不能填看是否在流程中，再决定继续或澄清
"""

import logging
import time

from customer_service.chitchat.handler import ChitChatHandler
from customer_service.domain.constants import (
    OBJECT_TYPE_ORDER,
    OBJECT_TYPE_PRODUCT,
    SESSION_IDLE_TIMEOUT_SECONDS,
    SLOT_ORDER_NUMBER,
    SLOT_PRODUCT_ID,
)
from customer_service.domain.messages import BotMessage, MessageType, ProcessResult, UserMessage
from customer_service.domain.state import DialogueState
from customer_service.knowledge.handler import KnowledgeHandler
from customer_service.plan.models import ClarifyReason
from customer_service.plan.turn_planner import TurnPlanner
from customer_service.plan.turn_validator import TurnPlanValidator
from customer_service.responder.clarify_responder import ClarifyResponder
from customer_service.task.command.models import Command, SetSlotsCommand
from customer_service.task.flow.flows import FlowsList
from customer_service.task.flow.steps import CollectFlowStep
from customer_service.task.handler import TaskHandler

logger = logging.getLogger(__name__)


class DialogueEngine:
    """
    对话引擎
    """

    def __init__(
        self,
        turn_planner: TurnPlanner,
        task_handler: TaskHandler,
        knowledge_handler: KnowledgeHandler,
        chitchat_handler: ChitChatHandler,
        turn_plan_validator: TurnPlanValidator,
        clarify_responder: ClarifyResponder,
    ) -> None:
        self.turn_planner = turn_planner
        self.task_handler = task_handler
        self.knowledge_handler = knowledge_handler
        self.chitchat_handler = chitchat_handler
        self.turn_plan_validator = turn_plan_validator
        self.clarify_responder = clarify_responder

    async def process_message(self, dialogue_state: DialogueState, user_message: UserMessage) -> ProcessResult:
        logger.info(
            "开始处理消息：sender_id=%s message_id=%s type=%s",
            user_message.sender_id,
            user_message.message_id,
            user_message.type.value,
        )
        # 1. 准备会话
        self._prepare_session(dialogue_state)

        # 2. 开启本轮 turn
        self._begin_turn(dialogue_state, user_message)

        # 3. 按消息类型分流
        if user_message.type is MessageType.TEXT:
            messages = await self._handle_text_message(dialogue_state)
        else:
            # 对象消息：先把"用户现在关注这个对象"记下来，再决定怎么回应
            if user_message.object is not None:
                dialogue_state.set_focused_object(user_message.object)
            messages = await self._handle_object_message(message=user_message, state=dialogue_state)

        # 4. 把本轮回复写入 turn 并提交
        dialogue_state.pending_turn.bot_messages.extend(messages)
        dialogue_state.commit_pending_turn()

        # 5. 组装返回结果
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages,
        )

    def _prepare_session(self, dialogue_state: DialogueState) -> None:
        """
        准备会话：没有就新建；超时 1 小时就重开；否则续期
        """
        session = dialogue_state.current_session()

        if session is None:
            dialogue_state.start_session()
            return

        now = time.time()
        if now - session.last_activity_at > SESSION_IDLE_TIMEOUT_SECONDS:
            logger.info("会话超时，开启新会话：sender_id=%s", dialogue_state.sender_id)
            dialogue_state.close_current_session()
            dialogue_state.reset_runtime_state_for_new_session()
            dialogue_state.start_session()
        else:
            session.last_activity_at = now

    def _begin_turn(self, dialogue_state: DialogueState, user_message: UserMessage) -> None:
        """
        开启本轮：先把用户消息放进 pending_turn
        """
        dialogue_state.begin_turn(user_message)

    async def _handle_text_message(self, dialogue_state: DialogueState) -> list[BotMessage]:
        """
        文本消息：LLM 出计划 -> 防幻觉校验 -> 按轨道分发
        """
        # 1. 调 LLM 生成本轮计划
        started_at = time.perf_counter()
        turn_plan = await self.turn_planner.predict(
            dialogue_state,
            self.task_handler.flows,
            self.knowledge_handler.knowledge_intents,
        )
        logger.debug("本轮计划生成耗时：%.2fs", time.perf_counter() - started_at)

        # 2. 防幻觉校验：不合法就澄清，不往下执行
        validation = self.turn_plan_validator.validate(
            state=dialogue_state,
            turn_plan=turn_plan,
            flow_list=self.task_handler.flows,
            intents=self.knowledge_handler.knowledge_intents,
        )
        if not validation.valid:
            logger.info("计划校验未通过，转澄清：reason=%s", validation.reason.value)
            return await self.clarify_responder.respond(
                state=dialogue_state,
                reason=validation.reason,
            )

        # 3. 按轨道分发
        if turn_plan.task is not None:
            logger.debug("进入 task 轨道：commands=%d", len(turn_plan.task.commands))
            return await self.task_handler.handle(
                commands=turn_plan.task.commands,
                state=dialogue_state,
            )
        elif turn_plan.knowledge is not None:
            logger.debug("进入 knowledge 轨道：intents=%s", turn_plan.knowledge.intents)
            return await self.knowledge_handler.handle(
                intents=turn_plan.knowledge.intents,
                state=dialogue_state,
            )
        else:
            logger.debug("进入 chitchat 轨道")
            return await self.chitchat_handler.handle(state=dialogue_state)

    async def _handle_object_message(
        self,
        message: UserMessage,
        state: DialogueState,
    ) -> list[BotMessage]:
        """
        对象消息三分支：
        A. 对象正好能填当前流程缺的槽 -> 转成 SetSlotsCommand，推进流程
        C. 在流程里但槽不匹配 -> 不打断，空命令让流程继续
        B. 不在任何流程里 -> 澄清"你想干嘛"
        """
        commands = self._resolve_object_commands(
            message=message,
            state=state,
            flows=self.task_handler.flows,
        )
        if commands:
            # 场景 A
            return await self.task_handler.handle(commands=commands, state=state)

        if state.active_task is not None:
            # 场景 C
            return await self.task_handler.handle(commands=[], state=state)

        # 场景 B
        return await self.clarify_responder.respond(
            state=state,
            reason=ClarifyReason.OBJECT_REQUIRES_INTENT,
        )

    def _resolve_object_commands(
        self,
        message: UserMessage,
        state: DialogueState,
        flows: FlowsList,
    ) -> list[Command]:
        """
        对象转命令：订单 -> order_number，商品 -> product_id
        """
        message_object = message.object
        if message_object is None:
            return []

        object_type = message_object.type.strip().lower()

        if object_type == OBJECT_TYPE_ORDER:
            if self._flow_has_unfilled_collect_slot(state, flows, SLOT_ORDER_NUMBER):
                return [
                    SetSlotsCommand(
                        command="set_slots",
                        slots={SLOT_ORDER_NUMBER: message_object.id},
                    )
                ]
            return []

        if object_type == OBJECT_TYPE_PRODUCT:
            if self._flow_has_unfilled_collect_slot(state, flows, SLOT_PRODUCT_ID):
                return [
                    SetSlotsCommand(
                        command="set_slots",
                        slots={SLOT_PRODUCT_ID: message_object.id},
                    )
                ]
            return []

        return []

    @staticmethod
    def _flow_has_unfilled_collect_slot(
        state: DialogueState,
        flows: FlowsList,
        slot_name: str,
    ) -> bool:
        """
        当前流程是否定义了名为 slot_name 的收集槽，且还没填？
        """
        active_task = state.active_task
        if active_task is None:
            return False

        flow = flows.get_flow_by_id(active_task.flow_id)
        if flow is None:
            return False

        if active_task.slots.get(slot_name):
            return False

        return any(isinstance(step, CollectFlowStep) and step.slot_name == slot_name for step in flow.steps)
