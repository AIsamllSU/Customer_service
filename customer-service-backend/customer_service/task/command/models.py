# customer_service/task/command/models.py

"""
业务命令模型

用户的自然语言动作会被 LLM 翻译成一条条"原子指令"：
- start_flow   开启一个新流程
- set_slots     给当前流程填写槽位
- cancel_flow   取消当前流程
- resume_flow   恢复之前挂起的流程
"""

from typing import Any

from pydantic import BaseModel


class Command(BaseModel):
    """
    所有命令的基类，只有 command 字段用来标识自己是哪种命令
    """

    command: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Command":
        """
        多态反序列化：按 command 字段挑对应的子类
        """
        clz = COMMAND_NAME_TO_CLASS[data["command"]]
        return clz(**data)


class StartFlowCommand(Command):
    """
    开启一个新流程，必须说清开哪个
    """

    flow: str


class SetSlotsCommand(Command):
    """
    填写一个或多个槽位
    """

    slots: dict[str, Any]


class CancelFlowCommand(Command):
    """
    取消当前流程，不需要额外信息
    """

    pass


class ResumeFlowCommand(Command):
    """
    恢复挂起的流程；不传 flow 时恢复最近挂起的那个
    """

    flow: str | None = None


COMMAND_NAME_TO_CLASS = {
    "start_flow": StartFlowCommand,
    "set_slots": SetSlotsCommand,
    "cancel_flow": CancelFlowCommand,
    "resume_flow": ResumeFlowCommand,
}


if __name__ == "__main__":
    dict_data1 = {"command": "start_flow", "flow": "refund_request"}
    dict_data2 = {"command": "set_slots", "slots": {"order_number": "10001"}}
    dict_data3 = {"command": "cancel_flow"}
    dict_data4 = {"command": "resume_flow", "flow": "refund_request"}

    for dict_data in (dict_data1, dict_data2, dict_data3, dict_data4):
        command = Command.from_dict(dict_data)
        print(command)
        print(type(command))
