# atguigu/api/app.py

"""
创建 FastAPI 实例，并通过 lifespan 管理应用生命周期：

- 启动时：初始化日志 + 数据库引擎 + 建表
- 运行中：yield 让出控制权，FastAPI 处理请求
- 关闭时：关闭数据库连接池
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from atguigu.api.routers.chat_router import router
from atguigu.conf.config import settings
from atguigu.conf.logging import configure_logging
from atguigu.infrastructure.database import close_db_engine, create_tables, init_db_engine
from atguigu.infrastructure.http_client import close_http_client, init_http_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 1. 应用启动
    configure_logging()
    logger.info("服务启动：初始化数据库连接池")
    init_db_engine()  # 自带连接池
    await create_tables()  # 确保 dialogue_states 表存在
    init_http_client()  # 电商中台 HTTP 客户端（知识检索 / 自定义 action 共用）
    logger.info("服务启动完成：host=%s port=%s", settings.app_host, settings.app_port)

    try:
        # 2. 进入 yield，FastAPI 开始接收请求
        yield
    finally:
        # 3. 应用关闭（正常退出与异常退出都会走到这里）
        await close_db_engine()
        await close_http_client()
        logger.info("服务已停止：数据库连接池与 HTTP 客户端已释放")


app = FastAPI(
    title="电商小二 AI 智能客服系统",
    description="电商客服对话后端：任务流编排 + 知识问答 + 防幻觉校验",
    lifespan=lifespan,
)

if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    兜底异常处理：记录完整堆栈，对外只返回通用提示，避免泄露内部细节。
    """
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部错误，请稍后重试"},
    )


app.include_router(router)
