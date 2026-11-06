# atguigu/task/action/registry.py

"""
Action 注册表：name -> Action 实例。

YAML 里写的是字符串名（如 action_lookup_order_status），
真正执行的是 Python 实例，注册表负责这层"字符串 -> 对象"的翻译。
"""

import logging

from atguigu.task.action.base import Action

logger = logging.getLogger(__name__)


class ActionRegistry:
    """
    动作注册表。
    """

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        """
        注册一个 action；同名重复注册时后者覆盖前者，并记录告警。
        """
        if action.name in self._actions:
            logger.warning("Action 重复注册，后注册的实例将覆盖前者：%s", action.name)
        self._actions[action.name] = action

    def get(self, name: str) -> Action:
        """
        按名字取 action 实例；不存在时抛 KeyError，由上层决定如何兜底。
        """
        action = self._actions.get(name)
        if action is None:
            raise KeyError(f"Unknown action '{name}'.")
        return action

    def names(self) -> list[str]:
        """
        返回已注册的动作名（排序后），用于启动日志与验证脚本。
        """
        return sorted(self._actions)
