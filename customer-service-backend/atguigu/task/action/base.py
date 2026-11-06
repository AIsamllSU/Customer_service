# atguigu/task/action/base.py

"""
Action 基类与统一返回结果。

约定：
- 每个 Action 子类必须声明唯一的 `name`（与 YAML 里 `action: xxx` 对齐）
- `run` 只负责"干活"，不直接修改 DialogueState
- 产物统一放在 ActionResult：要么是 messages（要说的话），要么是 slot_updates（要写回的槽位）
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from atguigu.domain.messages import BotMessage
from atguigu.domain.state import DialogueState


class ActionResult(BaseModel):
    """
    所有 Action 的统一返回结果。

    把副作用（改槽位）和输出（发消息）都收进一个不可变快照，
    由调用方（下一节的 FlowExecutor）统一写回 state，测试时也更容易断言。
    """

    messages: list[BotMessage] = Field(default_factory=list)  # 要发给用户的回复
    slot_updates: dict[str, Any] = Field(default_factory=dict)  # 要写回 state 的槽位


class Action(ABC):
    """
    所有动作的基类。
    """

    name: str  # 动作唯一名称，和 YAML 里的 action 字段对应

    @abstractmethod
    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        """
        执行动作。

        :param state: 当前对话状态（只读使用，不要在这里改 state）
        :param action_kwargs: YAML 里该 action 步骤的 args 参数
        :return: ActionResult
        """
        raise NotImplementedError
