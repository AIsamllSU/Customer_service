# customer_service/task/action/builtin/action_listen.py

"""
ActionListen：流程里的"暂停哨兵"。

它本身不产生任何回复，只作为"该停下来等用户输入了"的信号；
下一节 FlowExecutor 在推进循环里遇到它就会 break。
"""

import logging
from typing import Any

from customer_service.domain.constants import ACTION_LISTEN
from customer_service.domain.state import DialogueState
from customer_service.task.action.base import Action, ActionResult

logger = logging.getLogger(__name__)


class ActionListen(Action):
    """
    等待用户输入：什么都不做，返回空结果。
    """

    name = ACTION_LISTEN

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        logger.debug("action_listen：流程在此等待用户输入")
        return ActionResult()
