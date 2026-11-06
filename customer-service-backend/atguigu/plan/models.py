# atguigu/plan/models.py

"""
本轮计划的数据模型

TurnPlan 有三个轨道字段，每个要么是计划对象、要么是 None：
- task       办业务（装一串 commands）
- knowledge  咨询信息（装一串 intents）
- chitchat   闲聊（不需要参数）
"""

import json
from enum import StrEnum

from pydantic import BaseModel, Field

from atguigu.task.command.models import Command


class TaskTurnPlan(BaseModel):
    """
    业务任务轨道
    """

    commands: list[Command] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskTurnPlan":
        return cls(commands=[Command.from_dict(command_data) for command_data in data.get("commands", [])])


class KnowledgeTurnPlan(BaseModel):
    """
    信息咨询轨道
    """

    intents: list[str] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeTurnPlan":
        return cls(intents=data.get("intents", []))


class ChitchatTurnPlan(BaseModel):
    """
    闲聊轨道：不需要任何参数
    """

    pass


class TurnPlan(BaseModel):
    """
    本轮对话的规划结果
    """

    task: TaskTurnPlan | None = None
    knowledge: KnowledgeTurnPlan | None = None
    chitchat: ChitchatTurnPlan | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "TurnPlan":
        """
        dict -> TurnPlan
        """
        return cls(
            task=TaskTurnPlan.from_dict(data["task"]) if data.get("task") is not None else None,
            knowledge=KnowledgeTurnPlan.from_dict(data["knowledge"]) if data.get("knowledge") is not None else None,
            chitchat=ChitchatTurnPlan() if data.get("chitchat") is not None else None,
        )


class ClarifyReason(StrEnum):
    """
    校验失败的原因码：枚举值既是字符串，也能当枚举比较
    """

    MISSING_TRACK = "missing_track"
    MULTIPLE_TRACKS = "multiple_tracks"
    MISSING_TASK_COMMANDS = "missing_task_commands"
    MISSING_KNOWLEDGE_INTENT = "missing_knowledge_intent"
    MISSING_FOCUSED_OBJECT = "missing_focused_object"
    OBJECT_REQUIRES_INTENT = "object_requires_intent"
    INVALID_TASK_COMMANDS = "invalid_task_commands"
    MULTIPLE_TASK_FLOWS = "multiple_task_flows"
    UNKNOWN_TASK_FLOW = "unknown_task_flow"


class TurnPlanValidationResult(BaseModel):
    """
    校验结果：能不能执行 + 不能执行的原因
    """

    valid: bool
    reason: ClarifyReason | None = None


if __name__ == "__main__":
    json_str = """
    {
      "task": {
        "commands": [
          {"command": "start_flow", "flow": "refund_request"}
        ]
      },
      "knowledge": null,
      "chitchat": null
    }
    """

    turn_plan = TurnPlan.from_dict(json.loads(json_str))
    print(turn_plan)
    print(type(turn_plan))
