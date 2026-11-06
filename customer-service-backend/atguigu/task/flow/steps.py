"""
步骤（流程图里的"节点"）

四种步骤：
- StartFlowStep   流程起点
- EndFlowStep     流程终点
- ActionFlowStep  执行一个动作（回复 / 等待 / 查数据）
- CollectFlowStep 收集一个槽位（等于"问 + 等"）
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from atguigu.task.flow.links import (
    ConditionalLink,
    FallbackLink,
    FlowStepLink,
    StaticLink,
)


class ResponseDefinition(BaseModel):
    """
    响应定义：一句回复怎么生成
    static   -> 原样输出 text
    rephrase -> 用 prompt 让大模型改写 text
    """

    text: str  # AI 的回复，必填
    model: str = "static"  # 响应方式，可选，默认静态
    prompt: str | None = None  # rephrase 模式下给大模型的提示词


class FlowStepType(Enum):
    """
    流程的步骤类型
    """

    START = "start"
    END = "end"
    ACTION = "action"
    COLLECT = "collect"


class FlowStep(BaseModel):
    """
    流程步骤基类（模板）
    """

    id: str  # 步骤ID，必填
    type: FlowStepType  # 步骤类型，必填
    next: list[FlowStepLink] = Field(default_factory=list)  # 出边列表
    description: str = ""  # 步骤描述

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "FlowStep":
        """
        按 type 找到对应子类，再交给子类构造（多态分发 / 工厂模式）
        """
        step_type = step_data["type"]
        clz = STEP_TYPE_TO_CLASS[step_type]
        return clz.from_dict(step_data)

    @staticmethod
    def base_fields(base_data: dict[str, Any]) -> dict[str, Any]:
        """
        抽取所有子类共有的四个字段
        """
        return {
            "id": base_data["id"],
            "type": FlowStepType(base_data["type"]),
            "description": base_data.get("description", ""),
            "next": FlowStep.build_links(base_data["next"]),
        }

    @staticmethod
    def build_links(link_data: str | list[dict[str, Any]]) -> list[FlowStepLink]:
        """
        把 YAML 里的 next 翻译成边对象列表

        next 是字符串 -> StaticLink
        next 是列表 -> 含 if 的变 ConditionalLink，含 else 的变 FallbackLink
        """
        # 1. next 是字符串
        if isinstance(link_data, str):
            return [StaticLink(target=link_data)]

        # 2. next 是列表
        links = []
        for link_dict in link_data:
            if "if" in link_dict:
                links.append(
                    ConditionalLink(
                        target=link_dict["then"],
                        condition=link_dict["if"],
                    )
                )
            else:
                links.append(FallbackLink(target=link_dict["else"]))
        return links


class StartFlowStep(FlowStep):
    """
    流程步骤：开始
    """

    type: FlowStepType = FlowStepType.START

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "StartFlowStep":
        return cls(**FlowStep.base_fields(step_data))


class EndFlowStep(FlowStep):
    """
    流程步骤：结束
    """

    type: FlowStepType = FlowStepType.END

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "EndFlowStep":
        return cls(**FlowStep.base_fields(step_data))


class ActionFlowStep(FlowStep):
    """
    流程步骤：执行某个动作

    action_listen  -> 哨兵，等用户说话
    action_response-> 告诉用户一句话
    action_xxx     -> 查数据等业务动作
    """

    type: FlowStepType = FlowStepType.ACTION

    action: str  # 动作名称，必填
    # 动作参数，选填。通常是 dict；
    # 也允许写变量引用字符串，如 system_collect_information 里的 args: context.response
    args: dict | str = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "ActionFlowStep":
        return cls(
            **FlowStep.base_fields(step_data),
            action=step_data["action"],
            args=step_data.get("args", {}),
        )


class CollectFlowStep(FlowStep):
    """
    流程步骤：收集某个槽位

    槽位已有值 -> 直接走 next
    槽位缺失   -> 用 response 追问并等待
    """

    type: FlowStepType = FlowStepType.COLLECT

    slot_name: str  # 要收集的槽位名，必填
    response: ResponseDefinition  # 缺失时的追问话术，必填

    @classmethod
    def from_dict(cls, step_data: dict[str, Any]) -> "CollectFlowStep":
        return cls(
            **FlowStep.base_fields(step_data),
            slot_name=step_data["slot_name"],
            response=ResponseDefinition(**step_data["response"]),
        )


# 类型注册表：YAML 里的 type 字符串 -> 具体子类
STEP_TYPE_TO_CLASS = {
    "start": StartFlowStep,
    "action": ActionFlowStep,
    "collect": CollectFlowStep,
    "end": EndFlowStep,
}
