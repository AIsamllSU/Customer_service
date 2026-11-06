# customer_service/task/flow/executor.py

"""
FlowExecutor：把 YAML 流程、对话状态和 action 串起来的执行器。

两层循环：
- 外层 run_task                ：执行 action，遇到 action_listen 就停轮
- 内层 advance_until_action     ：沿 step.next 推进，直到遇到要执行的 action
"""

import logging
from typing import Any

from customer_service.domain.constants import (
    ACTION_LISTEN,
    OBJECT_TYPE_ORDER,
    OBJECT_TYPE_PRODUCT,
    SLOT_ORDER_NUMBER,
    SLOT_PRODUCT_ID,
    SYSTEM_FLOW_COLLECT_INFORMATION,
)
from customer_service.domain.contexts import CollectedSystemContext
from customer_service.domain.messages import BotMessage
from customer_service.domain.state import DialogueState
from customer_service.task.action.runner import ActionCall, ActionRunner
from customer_service.task.flow.flows import FlowsList
from customer_service.task.flow.links import ConditionalLink, FallbackLink, StaticLink
from customer_service.task.flow.steps import (
    ActionFlowStep,
    CollectFlowStep,
    EndFlowStep,
    FlowStep,
    StartFlowStep,
)

logger = logging.getLogger(__name__)

_REFERENCE_PREFIX_CONTEXT = "context."


class FlowExecutor:
    """
    流程执行器：推进 YAML 中定义的业务任务流程以及系统任务流程。
    """

    async def run_task(
        self,
        state: DialogueState,
        flows: FlowsList,
        action_runner: ActionRunner,
    ) -> list[BotMessage]:
        """
        执行当前任务直到需要等待用户输入（action_listen）。

        返回本轮要发给用户的消息。
        """
        messages: list[BotMessage] = []
        while True:
            # 1. 推进流程与内部 step，遇到 action 步骤时返回
            action_call = self.advance_until_action(state, flows)

            # 2. action_listen 表示该等下一轮用户输入了
            if action_call.action_name == ACTION_LISTEN:
                break

            # 3. 执行 action，并把产物写回 state
            action_result = await action_runner.run(action_call, state)
            if action_result.slot_updates:
                state.set_slots(action_result.slot_updates)
            messages.extend(action_result.messages)

        return messages

    def advance_until_action(self, state: DialogueState, flows: FlowsList) -> ActionCall:
        """
        沿流程推进，跳过不需要执行 action 的 step，直到遇到 action step。

        没有当前任务时返回 action_listen，表示只能等用户输入。
        """
        while True:
            # 1. 当前任务：系统过场优先
            current_active_task = state.current_active_task()
            if current_active_task is None:
                return ActionCall(action_name=ACTION_LISTEN)

            # 2. 按 flow_id / step_id 定位当前流程与步骤
            flow = flows.get_flow_by_id(current_active_task.flow_id)
            if flow is None:
                raise ValueError(f"未知流程：'{current_active_task.flow_id}'")

            step = flow.get_step_by_id(current_active_task.step_id)
            if step is None:
                raise ValueError(f"流程 '{flow.id}' 中不存在步骤：'{current_active_task.step_id}'")

            # 3. 处理当前 step；返回 None 表示继续推进
            action_call = self._run_step(state, step, flows)
            if action_call is not None:
                return action_call

    def _run_step(self, state: DialogueState, step: FlowStep, flows: FlowsList) -> ActionCall | None:
        """
        按 step 类型分发。

        返回 None 表示这一步不产生 action，继续推进；
        返回 ActionCall 表示该执行 action 了。
        """
        if isinstance(step, StartFlowStep):
            return self._run_start_step(step, state)
        if isinstance(step, EndFlowStep):
            return self._run_end_step(state)
        if isinstance(step, CollectFlowStep):
            return self._run_collect_step(step, state, flows)
        if isinstance(step, ActionFlowStep):
            return self._run_action_step(step, state)
        raise ValueError(f"不支持的步骤类型：{type(step).__name__}")

    # ------------------------------------------------------------------
    # 四种 step 的处理
    # ------------------------------------------------------------------
    def _run_start_step(self, step: StartFlowStep, state: DialogueState) -> None:
        """
        start 只是入口标记：把 step_id 推到下一步，交给内层循环继续。
        """
        self._advance_next_step(state, step)
        return None

    def _run_end_step(self, state: DialogueState) -> None:
        """
        end 结束当前流程：系统过场只清系统任务，业务任务清业务上下文。
        """
        if state.active_system_task:
            state.end_active_system_task()
        else:
            state.end_active_task()
        return None

    def _run_collect_step(
        self,
        step: CollectFlowStep,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        """
        collect：先尝试自动补槽；已有值就推进，缺值就启动系统追问流程。
        """
        # 1. 聚焦对象能提供就直接填
        self._try_to_fill_collect_slot_focused_object(state, step)

        # 2. 槽位已有值：直接推进
        if state.active_task.slots.get(step.slot_name):
            self._advance_next_step(state, step)
            return None

        # 3. 槽位缺值：启动系统过场，由 system_collect_information 追问
        system_flow = flows.get_flow_by_id(SYSTEM_FLOW_COLLECT_INFORMATION)
        if system_flow is None:
            raise ValueError(f"缺少系统流程配置：'{SYSTEM_FLOW_COLLECT_INFORMATION}'")

        state.start_active_system_task(
            CollectedSystemContext(
                flow_id=SYSTEM_FLOW_COLLECT_INFORMATION,
                step_id=system_flow.start_step().id,
                slot_name=step.slot_name,
                response=step.response.model_dump(mode="json"),
            )
        )
        return None

    def _run_action_step(self, step: ActionFlowStep, state: DialogueState) -> ActionCall:
        """
        action：先推进 step_id，再构造 ActionCall。

        顺序不能反：如果先返回再推进，外层执行完 action 后内层会停在同一个
        action step 上，造成死循环。
        """
        self._advance_next_step(state, step)
        return self._build_action_call(state, step)

    # ------------------------------------------------------------------
    # 推进与条件跳转
    # ------------------------------------------------------------------
    def _advance_next_step(self, state: DialogueState, step: FlowStep) -> None:
        """
        推进的本质：把当前任务的 step_id 改成下一个 step 的 id。
        """
        next_step_id = self._select_next_step(step, state)
        state.current_active_task().step_id = next_step_id

    def _select_next_step(self, step: FlowStep, state: DialogueState) -> str:
        """
        从 next 链接中挑选目标步骤。

        StaticLink 直接命中；ConditionalLink 看条件；FallbackLink 兜底。
        """
        for link in step.next:
            if isinstance(link, StaticLink):
                return link.target
            if isinstance(link, ConditionalLink) and self._eval_condition(state, link.condition):
                return link.target
            if isinstance(link, FallbackLink):
                return link.target

        raise ValueError(f"步骤 '{step.id}' 没有可用的 next 链接")

    def _eval_condition(self, state: DialogueState, condition: str) -> bool:
        """
        计算 YAML 里的条件表达式。

        data 只暴露 slots 与当前任务上下文，且禁用内置函数，避免条件字符串
        获得访问系统能力的机会。
        """
        current_active_task = state.current_active_task()
        data = {
            "slots": state.active_task.slots if state.active_task is not None else {},
            "context": current_active_task.model_dump(mode="json") if current_active_task is not None else {},
        }
        return bool(eval(condition, {"__builtins__": None}, data))

    # ------------------------------------------------------------------
    # 构造 ActionCall 与自动补槽
    # ------------------------------------------------------------------
    def _build_action_call(self, state: DialogueState, step: ActionFlowStep) -> ActionCall:
        """
        构造一次动作调用。

        args 有两种形态：
        - dict：直接作为 action_kwargs
        - 字符串引用：如 "context.response"，从当前任务上下文字段取值
        """
        action_kwargs: Any = step.args
        if isinstance(action_kwargs, str):
            action_kwargs = self._resolve_action_kwargs_reference(state, action_kwargs)
        return ActionCall(action_name=step.action, action_kwargs=action_kwargs)

    @staticmethod
    def _resolve_action_kwargs_reference(state: DialogueState, reference: str) -> Any:
        """
        解析 "context.xxx" 形式的参数引用。

        system_collect_information 只有一个，但每个 collect step 的问句不同；
        通过 context.response 把问句变成激活系统流时传入的参数。
        """
        if not reference.startswith(_REFERENCE_PREFIX_CONTEXT):
            raise ValueError(f"不支持的 action args 引用：'{reference}'")

        current_active_task = state.current_active_task()
        if current_active_task is None:
            raise ValueError(f"解析 '{reference}' 时没有当前任务上下文")

        field_name = reference[len(_REFERENCE_PREFIX_CONTEXT) :]
        data = current_active_task.model_dump(mode="json")
        if field_name not in data:
            raise ValueError(f"当前任务上下文没有字段：'{field_name}'")
        return data[field_name]

    @staticmethod
    def _try_to_fill_collect_slot_focused_object(state: DialogueState, step: CollectFlowStep) -> None:
        """
        用聚焦对象自动补槽，省掉一次追问。

        focused_object 跨 turn 持久化：用户先点订单卡片、后说"查物流"时，
        进入 collect 就不再重复问订单号。
        """
        if state.focused_object is None:
            return

        if step.slot_name == SLOT_ORDER_NUMBER and state.focused_object.type == OBJECT_TYPE_ORDER:
            state.set_slots({step.slot_name: state.focused_object.id})

        if step.slot_name == SLOT_PRODUCT_ID and state.focused_object.type == OBJECT_TYPE_PRODUCT:
            state.set_slots({step.slot_name: state.focused_object.id})
