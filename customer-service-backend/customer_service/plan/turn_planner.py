# customer_service/plan/turn_planner.py

"""
TurnPlanner：把当前对话状态整理成提示词，调 LLM，产出本轮计划 TurnPlan。
"""

import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from customer_service.conf.config import settings
from customer_service.domain.constants import HISTORY_WINDOW_TURNS
from customer_service.domain.state import DialogueState
from customer_service.infrastructure.llm import llm as default_llm
from customer_service.knowledge.intents import KNOWLEDGE_INTENTS, KnowledgeIntent
from customer_service.plan.errors import TurnPlanningError
from customer_service.plan.models import TurnPlan
from customer_service.prompts.history_builder import HistoryBuilder
from customer_service.prompts.loader import load_prompt
from customer_service.task.flow.flows import FlowsList

logger = logging.getLogger(__name__)


class TurnPlanner:
    """
    意图分析器
    作用：根据用户自然语言，调用 LLM 分析本轮走哪条轨道
    """

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        # 允许注入模型，测试时就能换成假模型，不依赖网络
        self.llm = llm or default_llm

    async def predict(
        self,
        state: DialogueState,
        flows_list: FlowsList,
        knowledge_intents: dict[str, KnowledgeIntent] | None = None,
    ) -> TurnPlan:
        # 1. 构建提示词
        inputs_prompt = self._build_prompt_inputs(state, flows_list, knowledge_intents or KNOWLEDGE_INTENTS)

        # 2. 调用 LLM 模型（失败会自动重试，最终失败抛 TurnPlanningError）
        turn_plan = await self._predict_from_prompt_inputs(inputs_prompt)

        # 3. 返回本轮计划
        return turn_plan

    def _build_prompt_inputs(
        self,
        state: DialogueState,
        flows_list: FlowsList,
        knowledge_intents: dict[str, KnowledgeIntent] | None = None,
    ) -> dict[str, Any]:
        """
        构建提示词输入参数（模板里的 7 个字段）
        """
        # 1. 用户消息
        user_message = HistoryBuilder.render_user_message(state.pending_turn.user_message)

        # 2. 历史对话：只取当前会话最近 10 轮，避免提示词过长
        session = state.current_session()
        recent_turns = session.turns[-HISTORY_WINDOW_TURNS:] if session is not None else []
        current_conversation = HistoryBuilder.build(recent_turns)

        # 3. 当前激活任务
        active_task_json = state.active_task.model_dump_json() if state.active_task is not None else None

        # 4. 中断（挂起）的任务
        interrupted_tasks_json = json.dumps(
            [paused_task.model_dump(mode="json") for paused_task in state.paused_tasks],
            ensure_ascii=False,
        )

        # 5. 页面点击卡片获取的对象
        focused_object_json = state.focused_object.model_dump_json() if state.focused_object is not None else None

        # 6. 流程清单：去掉 steps，只给 LLM 看"业务说明书"，省 token 也防干扰
        available_flows_json = json.dumps(
            {
                "flows": [
                    {key: value for key, value in flow.model_dump(mode="json").items() if key != "steps"}
                    for flow in flows_list.flows
                ]
            },
            ensure_ascii=False,
        )

        return {
            "user_message": user_message,
            "current_conversation": current_conversation,
            "active_task_json": active_task_json,
            "interrupted_tasks_json": interrupted_tasks_json,
            "focused_object_json": focused_object_json,
            "available_flows_json": available_flows_json,
            # 7. 知识意图清单：只给 id + 说明，约束 LLM 只能在注册表里选
            "knowledge_intents_json": json.dumps(
                [
                    {"id": intent.id, "description": intent.description}
                    for intent in (knowledge_intents or KNOWLEDGE_INTENTS).values()
                ],
                ensure_ascii=False,
            ),
        }

    async def _predict_from_prompt_inputs(self, inputs_prompt: dict[str, Any]) -> TurnPlan:
        """
        1. 加载提示词模板
        2. 格式化模板
        3. 调用模型（带有限次重试）
        4. 把模型返回的 JSON 解析成 TurnPlan
        """
        prompt_template_text = load_prompt("turn_plan")

        prompt_template = PromptTemplate.from_template(
            template=prompt_template_text,
            template_format="jinja2",
        )

        chain = prompt_template | self.llm | JsonOutputParser()

        last_error: Exception | None = None
        for attempt in range(1, settings.llm_max_attempts + 1):
            try:
                llm_response_dict: dict[str, Any] = await chain.ainvoke(inputs_prompt)
                return TurnPlan.from_dict(llm_response_dict)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM 本轮计划生成失败（第 %d/%d 次）：%s",
                    attempt,
                    settings.llm_max_attempts,
                    exc,
                )

        raise TurnPlanningError("LLM 规划服务暂时不可用") from last_error
