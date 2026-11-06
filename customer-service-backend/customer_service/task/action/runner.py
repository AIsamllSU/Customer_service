# customer_service/task/action/runner.py

"""
动作执行器：把一次 ActionCall 翻译成真正的 Action.run。

它不关心动作内部业务，只做三件事：查表 -> 调用 -> 返回。
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from customer_service.domain.state import DialogueState
from customer_service.task.action.base import ActionResult
from customer_service.task.action.registry import ActionRegistry

logger = logging.getLogger(__name__)


class ActionCall(BaseModel):
    """
    一次动作调用请求：调哪个 action + 传什么参数（由 FlowExecutor 构造）。
    """

    action_name: str
    action_kwargs: dict[str, Any] = Field(default_factory=dict)


class ActionRunner:
    """
    动作执行器。
    """

    def __init__(self, registry: ActionRegistry) -> None:
        self.registry = registry

    async def run(self, action_call: ActionCall, state: DialogueState) -> ActionResult:
        """
        执行一次动作。
        """
        action = self.registry.get(action_call.action_name)
        logger.debug("执行 action=%s", action_call.action_name)
        return await action.run(state, action_call.action_kwargs)
