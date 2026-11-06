"""
步骤之间的连接（流程图里的"边"）

三种边：
- StaticLink       固定跳转：next: ask_order_number
- ConditionalLink  条件跳转：next: [{if: 条件, then: 目标}]
- FallbackLink     兜底跳转：next: [{else: 目标}]
"""

from pydantic import BaseModel


class FlowStepLink(BaseModel):
    """
    模版边（基类）
    """

    target: str  # 下一步的 stepID


class StaticLink(FlowStepLink):
    """
    静态边：对应 next 的值是字符串
    """

    pass


class ConditionalLink(FlowStepLink):
    """
    条件边：对应 next: [{if: "...", then: step_id}]
    """

    condition: str  # 接收 if 中的条件表达式


class FallbackLink(FlowStepLink):
    """
    兜底边：对应 next: [{else: step_id}]
    """

    pass
