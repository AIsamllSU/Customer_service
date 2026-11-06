"""
流程容器

FlowSlot   一个槽位的定义
Flow       一个流程（id + 步骤 + 用到的槽位）
FlowsList  所有流程 + 全局槽位字典（加载器的最终产物）
"""

from pydantic import BaseModel, Field

from atguigu.task.flow.steps import FlowStep, StartFlowStep


class FlowSlot(BaseModel):
    """
    槽位定义
    """

    name: str  # 槽位名字
    type: str = "any"  # 槽位类型
    label: str = ""  # 槽位标签（给人看的）
    description: str = ""  # 槽位描述


class Flow(BaseModel):
    """
    流程
    """

    id: str  # 流程ID
    description: str = ""  # 流程说明
    steps: list[FlowStep] = Field(default_factory=list)  # 步骤列表
    slots: list[FlowSlot] = Field(default_factory=list)  # 本流程用到的槽位
    name: str | None = None  # 流程名称

    def start_step(self) -> StartFlowStep | None:
        """
        找到开始节点
        """
        for step in self.steps:
            if isinstance(step, StartFlowStep):
                return step
        return None

    def get_step_by_id(self, step_id: str) -> FlowStep | None:
        """
        按步骤ID取步骤
        """
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


class FlowsList(BaseModel):
    """
    流程列表（加载结果）
    """

    flows: list[Flow] = Field(default_factory=list)
    slots: dict[str, FlowSlot] = Field(default_factory=dict)

    def get_flow_by_id(self, flow_id: str) -> Flow | None:
        """
        按流程ID取流程
        """
        for flow in self.flows:
            if flow.id == flow_id:
                return flow
        return None
