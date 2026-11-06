# atguigu/task/action/builder.py

"""
动作装配：内置 action 手动注册 + 自定义 action 自动发现。

自动发现的意义：新增 custom/ 下的 Action 子类时，注册代码一行都不用改。
"""

import importlib
import inspect
import logging
import pkgutil

from atguigu.task.action.base import Action
from atguigu.task.action.builtin.action_listen import ActionListen
from atguigu.task.action.builtin.action_response import ActionResponse
from atguigu.task.action.registry import ActionRegistry
from atguigu.task.action.runner import ActionRunner

logger = logging.getLogger(__name__)

CUSTOM_ACTION_PACKAGE = "atguigu.task.action.custom"


def register_builtin_actions(action_runner: ActionRunner) -> None:
    """
    内置 action：数量固定、语义通用，手动注册。
    """
    action_runner.registry.register(ActionListen())
    action_runner.registry.register(ActionResponse())


def register_custom_actions(action_runner: ActionRunner) -> None:
    """
    扫描 custom/ 包，自动注册其中定义的 Action 子类。
    """
    package = importlib.import_module(CUSTOM_ACTION_PACKAGE)

    for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__, prefix=f"{package.__name__}."):
        # 只处理模块文件，不处理子包
        if is_pkg:
            continue

        module = importlib.import_module(module_name)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            # 只要 Action 子类，排除基类本身
            if not issubclass(obj, Action) or obj is Action:
                continue

            # 只注册"在本模块里定义"的类，避免 import 进来的类被重复注册
            if obj.__module__ != module.__name__:
                continue

            action_runner.registry.register(obj())


def build_action_runner() -> ActionRunner:
    """
    组装完整动作执行器：内置 + 自定义。
    """
    action_runner = ActionRunner(ActionRegistry())
    register_builtin_actions(action_runner)
    register_custom_actions(action_runner)
    logger.info("Action 注册完成：%s", ", ".join(action_runner.registry.names()))
    return action_runner
