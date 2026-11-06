# customer_service/plan/errors.py

"""
规划层异常：把"LLM 不可用 / 输出无法解析"包装成一个明确的类型，
让上层（Router）能区分"模型问题"和"代码 bug"。
"""


class TurnPlanningError(RuntimeError):
    """
    本轮计划生成失败：LLM 调用异常或返回内容无法解析为 TurnPlan。
    """
