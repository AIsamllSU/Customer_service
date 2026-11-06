"""
对话上下文模型 contexts.py

两类上下文：
- TaskContext：用户想做的事（业务任务）做到哪一步了
- SystemContext：系统插播的过场（任务开始 / 打断 / 取消 / 恢复 / 补槽位）
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class TaskContext(BaseModel):
    """
    业务任务上下文：一份"正在填的表单"
    """

    flow_id: str  # 业务任务的流程ID，如 refund_request
    step_id: str | None = None  # 业务任务执行到哪一步，如 ask_order_number
    slots: dict = {}  # 已收集到的槽位数据，如 {"order_number": "A001"}


class SystemContext(BaseModel):
    """
    系统流程上下文：所有系统过场的公共字段
    """

    flow_id: str  # 系统流程的流程ID
    step_id: str | None = None  # 系统流程当前执行的步骤ID


class StartedSystemContext(SystemContext):
    """
    流程开始
    """

    started_flow_id: str = ""  # 新开始的业务任务ID
    started_flow_name: str = ""  # 新开始的业务任务名字
    # Literal 把 flow_id 固定成一个字面量，作为区分联合类型的"身份标签"
    flow_id: Literal["system_task_started"] = "system_task_started"


class InterruptedSystemContext(SystemContext):
    """
    流程中断
    """

    interrupted_flow_id: str = ""  # 被中断的旧业务任务ID
    interrupted_flow_name: str = ""  # 被中断的旧业务任务名字
    started_flow_id: str = ""  # 新开始的业务任务ID
    started_flow_name: str = ""  # 新开始的业务任务名字
    flow_id: Literal["system_task_interrupted"] = "system_task_interrupted"


class CanceledSystemContext(SystemContext):
    """
    流程取消
    """

    canceled_flow_id: str = ""  # 被取消的业务任务ID
    canceled_flow_name: str = ""  # 被取消的业务任务名字
    flow_id: Literal["system_task_canceled"] = "system_task_canceled"


class ResumedSystemContext(SystemContext):
    """
    流程恢复
    """

    resumed_flow_id: str = ""  # 被恢复的业务任务ID
    resumed_flow_name: str = ""  # 被恢复的业务任务名字
    flow_id: Literal["system_task_resumed"] = "system_task_resumed"


class CollectedSystemContext(SystemContext):
    """
    系统流程收集槽位信息
    """

    slot_name: str = ""  # 收集的槽位名
    response: dict = {}  # 例如 {"text": "请告诉我你的订单号"}
    flow_id: Literal["system_collect_information"] = "system_collect_information"


# 五个子类合成一个"联合类型"，并声明用 flow_id 来区分到底是谁
SystemContextUnion = Annotated[
    StartedSystemContext
    | InterruptedSystemContext
    | CanceledSystemContext
    | ResumedSystemContext
    | CollectedSystemContext,
    Field(discriminator="flow_id"),
]

# 适配器：给"非 BaseModel 类型"（这里是联合类型）提供 validate / dump 能力
system_context_adapter = TypeAdapter(SystemContextUnion)


if __name__ == "__main__":
    obj1 = StartedSystemContext(
        flow_id="system_task_started",
        step_id="12",
        started_flow_id="21",
        started_flow_name="22",
    )
    data1 = obj1.model_dump(mode="json")

    obj2 = InterruptedSystemContext(
        flow_id="system_task_interrupted",
        step_id="12",
        started_flow_id="21",
        started_flow_name="22",
        interrupted_flow_id="31",
        interrupted_flow_name="32",
    )
    data2 = obj2.model_dump(mode="json")

    print(data1)
    print(type(data1))
    print(data2)
    print(type(data2))

    data_list = [data1, data2]

    # 反序列化方式一：知道具体子类时，直接用子类
    obj1 = StartedSystemContext.model_validate(data1)
    print(obj1)
    print(type(obj1))

    obj2 = InterruptedSystemContext.model_validate(data2)
    print(obj2)
    print(type(obj2))

    # 反序列化方式二：不知道具体子类时，交给适配器按 flow_id 自动挑选
    obj_list = [system_context_adapter.validate_python(data) for data in data_list]
    print(obj_list)
    for obj in obj_list:
        print(type(obj).__name__)
