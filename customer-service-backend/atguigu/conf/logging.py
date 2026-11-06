# atguigu/conf/logging.py

"""
日志配置：统一入口，避免各模块各自 `basicConfig`。

生产环境建议由部署平台注入 `LOG_LEVEL`；本地默认 INFO。
"""

import logging
import sys

from atguigu.conf.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    """
    初始化根日志器（幂等，可重复调用）。

    使用 `force=False`：如果运行环境（如 pytest、uvicorn）已经配置过日志，
    就尊重外部配置，避免把测试框架的日志捕获处理器移除。
    """
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        stream=sys.stdout,
    )
