# atguigu/task/command/processor.py

"""
CommandProcessor：TaskHandler 的第一阶段

它只做一件事：把 LLM 产出的命令，按顺序真正"落到" DialogueState 上。
- start_flow   开新流程 / 打断当前流程 / 从暂停栈恢复
- set_slots    给当前活跃任务填槽
- cancel_flow  丢掉当前活跃任务
- resume_flow  把暂停栈里的任务拿回来

第二阶段（FlowExecutor，按 YAML 推进流程并生成回复）由 TaskHandler 交给执行器完成。
"""

import logging

from atguigu.domain.constants import (
    SYSTEM_FLOW_CANCELED,
    SYSTEM_FLOW_INTERRUPTED,
    SYSTEM_FLOW_RESUMED,
    SYSTEM_FLOW_STARTED,
)
from atguigu.domain.contexts import (
    CanceledSystemContext,
    InterruptedSystemContext,
    ResumedSystemContext,
    StartedSystemContext,
    TaskContext,
)
from atguigu.domain.state import DialogueState
from atguigu.task.command.models import (
    CancelFlowCommand,
    Command,
    ResumeFlowCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from atguigu.task.flow.flows import Flow, FlowsList

logger = logging.getLogger(__name__)


class CommandProcessor:
    def run(
        self,
        commands: list[Command],
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        """
        把命令应用到 state

        一轮可能有多条命令（如 start_flow + set_slots），必须按顺序逐条应用：
        先开任务，后面的 set_slots 才有地方填。
        """
        for command in commands:
            logger.info("应用命令：%s", command.command)
            self._apply(command, state, flows)

    def _apply(
        self,
        command: Command,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        """
        按命令类型分发到对应的处理方法
        """
        if isinstance(command, StartFlowCommand):
            self._handle_start_flow(command, state, flows)
        elif isinstance(command, SetSlotsCommand):
            self._handle_set_slots(command, state)
        elif isinstance(command, CancelFlowCommand):
            self._handle_cancel_flow(state, flows)
        elif isinstance(command, ResumeFlowCommand):
            self._handle_resume_flow(command, state, flows)

    # ------------------------------------------------------------------
    # 开启流程：五种处境（有无活跃任务 × 目标在不在暂停栈）
    # ------------------------------------------------------------------
    def _handle_start_flow(
        self,
        command: StartFlowCommand,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        """
        开启业务任务
        """

        # 0. 新业务任务开始前，先清掉当前还没说完的系统过场
        state.end_active_system_task()

        # 1. 防御：不允许直接启动 system_ 开头的内部流程
        if command.flow.startswith("system_"):
            raise ValueError(f"不能直接启动系统流程：'{command.flow}'")

        # 2. 校验：流程必须存在
        target_flow = flows.get_flow_by_id(command.flow)
        if target_flow is None:
            raise ValueError(f"未知流程：'{command.flow}'")

        # 3. 校验：流程必须有起点
        start_step = target_flow.start_step()
        if start_step is None:
            raise ValueError(f"流程 '{command.flow}' 没有开始步骤")

        active_task = state.active_task

        # ===== 情况一：当前有活跃任务 =====
        if active_task is not None:
            # 1.1 同一个流程：已经在办，不重复启动
            if active_task.flow_id == command.flow:
                return

            # 1.2 不同流程：先把当前任务挂起
            interrupted_flow_id = active_task.flow_id
            interrupted_flow_name = self._readable_flow_name(interrupted_flow_id, flows)
            state.interrupted_active_task()
            logger.info("挂起当前任务：flow_id=%s", interrupted_flow_id)

            # 1.3 要开的流程如果在暂停栈里，就恢复它（保留旧进度和槽位）
            if not state.resumed_active_task(command.flow):
                # 不在暂停栈 -> 从零新建
                state.start_active_task(
                    TaskContext(
                        flow_id=command.flow,
                        step_id=start_step.id,
                    )
                )
                logger.info("新建任务：flow_id=%s step_id=%s", command.flow, start_step.id)

            # 1.4 激活"打断"过场
            self._activate_interrupted_system_flow(
                state=state,
                flows=flows,
                interrupted_flow_id=interrupted_flow_id,
                interrupted_flow_name=interrupted_flow_name,
                started_flow_id=command.flow,
                started_flow_name=self._readable_flow_name(command.flow, flows),
            )
            return

        # ===== 情况二：当前没有活跃任务 =====
        # 2.1 要开的流程之前被挂起过 -> 直接恢复
        if state.resumed_active_task(command.flow):
            self._activate_resumed_system_flow(
                state=state,
                flows=flows,
                resumed_flow_id=command.flow,
                resumed_flow_name=self._readable_flow_name(command.flow, flows),
            )
            return

        # 2.2 从没做过 -> 新建
        state.start_active_task(
            TaskContext(
                flow_id=command.flow,
                step_id=start_step.id,
            )
        )
        logger.info("新建任务：flow_id=%s step_id=%s", command.flow, start_step.id)
        self._activate_started_system_flow(
            state=state,
            flows=flows,
            started_flow_id=command.flow,
            started_flow_name=self._readable_flow_name(command.flow, flows),
        )

    # ------------------------------------------------------------------
    # 填槽位：最简单，有活跃任务才填
    # ------------------------------------------------------------------
    def _handle_set_slots(self, command: SetSlotsCommand, state: DialogueState) -> None:
        """
        填写槽位

        没有活跃任务时什么都不做——命令本身没有错，只是无处可填。
        """
        if state.active_task is not None:
            state.set_slots(command.slots)
            logger.info("填写槽位：%s", list(command.slots.keys()))
        else:
            logger.info("没有活跃任务，忽略填槽命令：%s", list(command.slots.keys()))

    # ------------------------------------------------------------------
    # 取消流程：清空当前任务 + 取消过场
    # ------------------------------------------------------------------
    def _handle_cancel_flow(self, state: DialogueState, flows: FlowsList) -> None:
        """
        取消当前活跃任务

        取消 = 丢弃（不留在暂停栈），和"打断"（挂起）是一对相反的操作。
        """
        active_task = state.active_task
        # 没有任务可取消：直接返回，避免把 None.flow_id 读崩
        if active_task is None:
            return

        canceled_flow_id = active_task.flow_id
        canceled_flow_name = self._readable_flow_name(canceled_flow_id, flows)

        # 需求：先清空 active_task 和 active_system_task
        state.cancel_active_task()
        logger.info("取消任务：flow_id=%s", canceled_flow_id)

        # 再激活"取消"过场
        state.start_active_system_task(
            CanceledSystemContext(
                flow_id=SYSTEM_FLOW_CANCELED,
                step_id=self._system_flow(flows, SYSTEM_FLOW_CANCELED).start_step().id,
                canceled_flow_id=canceled_flow_id,
                canceled_flow_name=canceled_flow_name,
            )
        )

    # ------------------------------------------------------------------
    # 恢复流程：指名 / 不指名 × 有无活跃任务
    # ------------------------------------------------------------------
    def _handle_resume_flow(
        self,
        command: ResumeFlowCommand,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        """
        恢复挂起的流程
        """

        # ===== 第一步：确定要恢复哪个流程 =====
        if command.flow is not None:
            # 指名恢复：校验流程存在
            target_flow = flows.get_flow_by_id(command.flow)
            if target_flow is None:
                raise ValueError(f"未知流程：'{command.flow}'")
            target_flow_id = target_flow.id
            target_flow_name = target_flow.name or target_flow.id
        else:
            # 不指名：取暂停栈栈顶（最近挂起的那个）
            if not state.paused_tasks:
                return
            top_paused = state.paused_tasks[-1]
            target_flow_id = top_paused.flow_id
            target_flow_name = self._readable_flow_name(target_flow_id, flows)

        # ===== 第二步：按"当前有没有活跃任务"恢复 =====
        active_task = state.active_task

        if active_task is not None:
            # 已经在办目标流程，不重复
            if active_task.flow_id == target_flow_id:
                return

            # 先把当前任务挂起，再恢复目标
            interrupted_flow_id = active_task.flow_id
            interrupted_flow_name = self._readable_flow_name(interrupted_flow_id, flows)
            state.interrupted_active_task()

            if not state.resumed_active_task(target_flow_id):
                # 恢复失败 -> 回退：把刚挂起的当前任务拿回来，当作什么都没发生
                state.resumed_active_task()
                return

            self._activate_interrupted_system_flow(
                state=state,
                flows=flows,
                interrupted_flow_id=interrupted_flow_id,
                interrupted_flow_name=interrupted_flow_name,
                started_flow_id=target_flow_id,
                started_flow_name=target_flow_name,
            )
            return

        # 没有活跃任务：直接恢复
        if not state.resumed_active_task(target_flow_id):
            return

        resumed_task = state.active_task
        self._activate_resumed_system_flow(
            state=state,
            flows=flows,
            resumed_flow_id=resumed_task.flow_id,
            resumed_flow_name=self._readable_flow_name(resumed_task.flow_id, flows),
        )

    # ------------------------------------------------------------------
    # 辅助：流程显示名 + 三个"激活系统过场"
    # ------------------------------------------------------------------
    @staticmethod
    def _readable_flow_name(flow_id: str, flows: FlowsList) -> str:
        """
        把 flow_id 转成给人看的中文名；查不到就退回 flow_id，保证不崩
        """
        flow = flows.get_flow_by_id(flow_id)
        return (flow.name or flow_id) if flow else flow_id

    @staticmethod
    def _system_flow(flows: FlowsList, flow_id: str) -> Flow:
        """
        获取内部系统流程；配置缺失属于部署错误，直接暴露出来
        """
        flow = flows.get_flow_by_id(flow_id)
        if flow is None:
            raise ValueError(f"缺少系统流程配置：'{flow_id}'")
        return flow

    @staticmethod
    def _activate_started_system_flow(
        state: DialogueState,
        flows: FlowsList,
        started_flow_id: str,
        started_flow_name: str,
    ) -> None:
        """
        新建任务：说"好的，我们先处理 XX"
        """
        system_flow = CommandProcessor._system_flow(flows, SYSTEM_FLOW_STARTED)
        state.start_active_system_task(
            StartedSystemContext(
                flow_id=SYSTEM_FLOW_STARTED,
                step_id=system_flow.start_step().id,
                started_flow_id=started_flow_id,
                started_flow_name=started_flow_name,
            )
        )
        logger.debug("激活开始过场：flow_id=%s", started_flow_id)

    @staticmethod
    def _activate_interrupted_system_flow(
        state: DialogueState,
        flows: FlowsList,
        interrupted_flow_id: str,
        interrupted_flow_name: str,
        started_flow_id: str,
        started_flow_name: str,
    ) -> None:
        """
        打断旧任务：说"先把 XX 放一放，先处理 YY"
        """
        system_flow = CommandProcessor._system_flow(flows, SYSTEM_FLOW_INTERRUPTED)
        state.start_active_system_task(
            InterruptedSystemContext(
                flow_id=SYSTEM_FLOW_INTERRUPTED,
                step_id=system_flow.start_step().id,
                interrupted_flow_id=interrupted_flow_id,
                interrupted_flow_name=interrupted_flow_name,
                started_flow_id=started_flow_id,
                started_flow_name=started_flow_name,
            )
        )
        logger.debug("激活打断过场：%s -> %s", interrupted_flow_id, started_flow_id)

    @staticmethod
    def _activate_resumed_system_flow(
        state: DialogueState,
        flows: FlowsList,
        resumed_flow_id: str,
        resumed_flow_name: str,
    ) -> None:
        """
        恢复任务：说"好的，我们继续刚才的 XX"
        """
        system_flow = CommandProcessor._system_flow(flows, SYSTEM_FLOW_RESUMED)
        state.start_active_system_task(
            ResumedSystemContext(
                flow_id=SYSTEM_FLOW_RESUMED,
                step_id=system_flow.start_step().id,
                resumed_flow_id=resumed_flow_id,
                resumed_flow_name=resumed_flow_name,
            )
        )
        logger.debug("激活恢复过场：flow_id=%s", resumed_flow_id)
