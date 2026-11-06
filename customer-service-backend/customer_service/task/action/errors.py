# customer_service/task/action/errors.py

"""
动作层异常：把"参数缺失 / 模式不支持 / LLM 调用失败"包装成明确类型，
方便下一节 FlowExecutor 统一兜底，而不是让各种 KeyError、AttributeError 直接冒到接口层。
"""


class ActionError(RuntimeError):
    """
    动作执行失败：动作内部可预期但无法继续的错误（如 LLM 调用失败）。
    """


class ActionConfigError(ActionError):
    """
    动作参数非法：缺少必填参数、mode 不支持等配置错误。
    """
