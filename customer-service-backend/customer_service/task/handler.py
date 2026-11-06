# customer_service/task/handler.py

"""
TaskHandler：task 轨道的执行入口，两阶段的协调者。

① CommandProcessor：把命令应用到 DialogueState
② FlowExecutor   ：按 YAML 推进流程、执行 action、生成回复
"""

import logging

from customer_service.domain.messages import BotMessage
from customer_service.domain.state import DialogueState
from customer_service.task.action.runner import ActionRunner
from customer_service.task.command.models import Command
from customer_service.task.command.processor import CommandProcessor
from customer_service.task.flow.executor import FlowExecutor
from customer_service.task.flow.flows import FlowsList

logger = logging.getLogger(__name__)


class TaskHandler:
    def __init__(
        self,
        flows: FlowsList,
        command_processor: CommandProcessor,
        action_runner: ActionRunner,
        flow_executor: FlowExecutor,
    ) -> None:
        self.flows = flows
        self.command_processor = command_processor
        self.action_runner = action_runner
        self.flow_executor = flow_executor

    async def handle(self, commands: list[Command], state: DialogueState) -> list[BotMessage]:
        """
        处理一轮任务

        :param commands: LLM 产出的命令列表，可能是空列表
        :param state: 对话状态
        :return: 本轮要回复的消息
        """
        # 阶段1：把命令应用到 state（建任务 / 填槽 / 取消 / 恢复 / 挂起）
        logger.debug("TaskHandler 阶段1 开始：commands=%d", len(commands))
        self.command_processor.run(commands, state, self.flows)

        # 阶段2：推进流程、执行 action、收集本轮回复
        logger.debug("TaskHandler 阶段2 开始：推进流程")
        return await self.flow_executor.run_task(state, self.flows, self.action_runner)
