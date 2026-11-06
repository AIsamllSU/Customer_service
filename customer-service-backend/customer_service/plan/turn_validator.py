# customer_service/plan/turn_validator.py

"""
TurnPlanValidator：防幻觉校验

职责只有一个：检查 TurnPlan 能不能执行，不能就给出原因码。
它不生成任何回复话术——那是 ClarifyResponder 的事。
"""

from customer_service.domain.state import DialogueState
from customer_service.knowledge.intents import KnowledgeIntent
from customer_service.plan.models import ClarifyReason, TurnPlan, TurnPlanValidationResult
from customer_service.task.command.models import (
    CancelFlowCommand,
    ResumeFlowCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from customer_service.task.flow.flows import FlowsList


class TurnPlanValidator:
    def validate(
        self,
        state: DialogueState,
        turn_plan: TurnPlan,
        flow_list: FlowsList,
        intents: dict[str, KnowledgeIntent],
    ) -> TurnPlanValidationResult:
        # 1. 命中了几个轨道
        active_tracks = self._active_tracks(turn_plan)

        # 2. 一个都没有 -> 让用户说想干嘛
        if not active_tracks:
            return self._reject(ClarifyReason.MISSING_TRACK)

        # 3. 命中多个 -> 让用户先选一个
        if len(active_tracks) > 1:
            return self._reject(ClarifyReason.MULTIPLE_TRACKS)

        # 4. 只命中一个，进入对应轨道的细查
        active_track = active_tracks[0]

        if active_track == "task":
            return self._validate_task(turn_plan, flow_list)

        if active_track == "knowledge":
            return self._validate_knowledge(state, turn_plan, intents)

        # 闲聊不需要任何校验
        return TurnPlanValidationResult(valid=True)

    @staticmethod
    def _active_tracks(turn_plan: TurnPlan) -> list[str]:
        """
        把非 null 的轨道名收集成列表
        """
        active_tracks: list[str] = []
        if turn_plan.task is not None:
            active_tracks.append("task")

        if turn_plan.knowledge is not None:
            active_tracks.append("knowledge")

        if turn_plan.chitchat is not None:
            active_tracks.append("chitchat")

        return active_tracks

    @staticmethod
    def _reject(reason: ClarifyReason) -> TurnPlanValidationResult:
        return TurnPlanValidationResult(valid=False, reason=reason)

    def _validate_task(self, turn_plan: TurnPlan, flows: FlowsList) -> TurnPlanValidationResult:
        """
        task 轨道四重校验
        """
        task_plan = turn_plan.task

        # 第一重：commands 不能为空
        if task_plan is None or not task_plan.commands:
            return self._reject(ClarifyReason.MISSING_TASK_COMMANDS)

        # 第二重：每条命令都得是认识的类型
        allowed = (StartFlowCommand, ResumeFlowCommand, CancelFlowCommand, SetSlotsCommand)
        if not all(isinstance(command, allowed) for command in task_plan.commands):
            return self._reject(ClarifyReason.INVALID_TASK_COMMANDS)

        # 第三重：一次不能开多个流程
        start_commands = [command for command in task_plan.commands if isinstance(command, StartFlowCommand)]
        if len(start_commands) > 1:
            return self._reject(ClarifyReason.MULTIPLE_TASK_FLOWS)

        # 第四重：要开的流程必须真实存在（最关键的防幻觉检查）
        if start_commands:
            flow = flows.get_flow_by_id(start_commands[0].flow)
            if flow is None:
                return self._reject(ClarifyReason.UNKNOWN_TASK_FLOW)

        return TurnPlanValidationResult(valid=True)

    def _validate_knowledge(
        self,
        state: DialogueState,
        turn_plan: TurnPlan,
        intents: dict[str, KnowledgeIntent],
    ) -> TurnPlanValidationResult:
        """
        knowledge 轨道校验：意图非空 + 需要对象的意图必须有对应对象
        """
        knowledge_plan = turn_plan.knowledge
        if knowledge_plan is None or not knowledge_plan.intents:
            return self._reject(ClarifyReason.MISSING_KNOWLEDGE_INTENT)

        focused_object = state.focused_object
        for intent in knowledge_plan.intents:
            intent_meta = intents.get(intent)
            # LLM 编了一个注册表里没有的意图，同样是幻觉
            if intent_meta is None:
                return self._reject(ClarifyReason.MISSING_KNOWLEDGE_INTENT)

            required_object = intent_meta.requires_object
            if required_object is not None and (focused_object is None or focused_object.type != required_object):
                return self._reject(ClarifyReason.MISSING_FOCUSED_OBJECT)

        return TurnPlanValidationResult(valid=True)
