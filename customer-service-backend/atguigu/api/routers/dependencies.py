# atguigu/api/routers/dependencies.py

"""
依赖注入：把"创建 session / Repository / Engine / Service"的活交给 FastAPI。

调用链顺序：
1. get_session() 打开 session 并 yield
2. get_dialogue_state_repository() 拿到 session，创建 Repository
3. get_dialogue_service() 拿到 Repository 和 Engine，创建 Service
4. 路由函数执行完毕后，回到 get_session() 的 yield 之后，自动关闭 session
"""

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from atguigu.chitchat.handler import ChitChatHandler
from atguigu.chitchat.responder import ChitChatResponder
from atguigu.engine.dialogue_engine import DialogueEngine
from atguigu.infrastructure import database
from atguigu.knowledge.handler import KnowledgeHandler
from atguigu.knowledge.intents import KNOWLEDGE_INTENTS
from atguigu.knowledge.providers import FAQProvider, OrderAPIProvider, ProductAPIProvider, RAGProvider
from atguigu.knowledge.registry import KnowledgeProviderRegistry
from atguigu.knowledge.responder import KnowledgeResponder
from atguigu.plan.turn_planner import TurnPlanner
from atguigu.plan.turn_validator import TurnPlanValidator
from atguigu.repository.dialogue_state_repository import DialogueStateRepository
from atguigu.responder.clarify_responder import ClarifyResponder
from atguigu.service.dialogue_service import DialogueService
from atguigu.task.action.builder import build_action_runner
from atguigu.task.action.runner import ActionRunner
from atguigu.task.command.processor import CommandProcessor
from atguigu.task.flow.executor import FlowExecutor
from atguigu.task.flow.flows import FlowsList
from atguigu.task.flow.loader import FlowLoader
from atguigu.task.handler import TaskHandler

BASE_PATH = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def load_flows() -> FlowsList:
    """
    流程定义是只读配置：进程内加载一次即可，避免每个请求都解析 YAML。
    """
    loader = FlowLoader()
    return loader.load_many(
        [
            BASE_PATH / "flow_config" / "user_flows.yml",
            BASE_PATH / "flow_config" / "system_flows.yml",
        ]
    )


@lru_cache(maxsize=1)
def load_action_runner() -> ActionRunner:
    """
    动作实例是只读装配结果：进程内构建一次即可，避免每个请求都扫描 custom 包。
    """
    return build_action_runner()


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    每个请求一个数据库会话，请求结束自动关闭。
    """
    if database.async_session is None:
        raise RuntimeError("数据库尚未初始化，请确认应用已启动 lifespan")
    async with database.async_session() as session:
        yield session


async def get_dialogue_state_repository(session: AsyncSession = Depends(get_session)) -> DialogueStateRepository:
    return DialogueStateRepository(session=session)


async def get_dialogue_engine() -> DialogueEngine:
    """
    组装真引擎：TurnPlanner（调 LLM）+ TaskHandler（持有一份流程清单）
              + TurnPlanValidator（防幻觉校验）+ ClarifyResponder（澄清回复）
    """
    return DialogueEngine(
        turn_planner=TurnPlanner(),
        task_handler=TaskHandler(
            flows=load_flows(),
            command_processor=CommandProcessor(),
            action_runner=load_action_runner(),
            flow_executor=FlowExecutor(),
        ),
        knowledge_handler=KnowledgeHandler(
            knowledge_intents=KNOWLEDGE_INTENTS,
            provider_registry=KnowledgeProviderRegistry(
                [
                    ProductAPIProvider(),
                    OrderAPIProvider(),
                    FAQProvider(),
                    RAGProvider(),
                ]
            ),
            knowledge_responder=KnowledgeResponder(),
        ),
        chitchat_handler=ChitChatHandler(ChitChatResponder()),
        turn_plan_validator=TurnPlanValidator(),
        clarify_responder=ClarifyResponder(),
    )


async def get_dialogue_service(
    dialogue_engine: DialogueEngine = Depends(get_dialogue_engine),
    dialogue_state_repository: DialogueStateRepository = Depends(get_dialogue_state_repository),
) -> DialogueService:
    return DialogueService(
        dialogue_engine=dialogue_engine,
        dialogue_state_repository=dialogue_state_repository,
    )
