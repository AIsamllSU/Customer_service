# customer_service/task/action/builtin/action_response.py

"""
ActionResponse：所有"对用户说话"的动作，支持三种模式。

static   -> 直接渲染 YAML 里的文案模板，不调 LLM
rephrase -> 先渲染底稿，再让 LLM 润色（失败时退回底稿）
generate -> 没有底稿，完全由 LLM 按 prompt 生成（失败时给固定兜底话术）
"""

import logging
from typing import Any

from jinja2 import Template
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from customer_service.domain.constants import (
    ACTION_GENERATE_FALLBACK_TEXT,
    ACTION_RESPONSE,
    RESPONSE_MODE_GENERATE,
    RESPONSE_MODE_REPHRASE,
    RESPONSE_MODE_STATIC,
)
from customer_service.domain.messages import BotMessage
from customer_service.domain.state import DialogueState
from customer_service.infrastructure.llm import llm as default_llm
from customer_service.prompts.history_builder import HistoryBuilder
from customer_service.task.action.base import Action, ActionResult
from customer_service.task.action.errors import ActionConfigError, ActionError

logger = logging.getLogger(__name__)


def _require_text(action_kwargs: dict[str, Any], key: str) -> str:
    """
    取必填字符串参数；缺失或空白时抛配置错误，避免 KeyError 直接冒到接口层。
    """
    value = action_kwargs.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ActionConfigError(f"action_response 缺少必填参数：{key}")
    return value


class ActionResponse(Action):
    """
    生成一条回复。

    允许注入 llm，测试时用假模型即可离线运行。
    """

    name = ACTION_RESPONSE

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        self.llm = llm or default_llm

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        mode = action_kwargs.get("mode", RESPONSE_MODE_STATIC)

        if mode == RESPONSE_MODE_STATIC:
            text = _require_text(action_kwargs, "text")
            return ActionResult(messages=[BotMessage(text=self._render_text(text, state))])

        if mode == RESPONSE_MODE_REPHRASE:
            text = _require_text(action_kwargs, "text")
            prompt_text = _require_text(action_kwargs, "prompt")
            rendered_text = self._render_text(text, state)
            try:
                reply = await self._call_llm(prompt_text, state, rendered_text)
            except ActionError:
                logger.warning("rephrase 润色失败，退回渲染后的底稿")
                reply = rendered_text
            return ActionResult(messages=[BotMessage(text=reply)])

        if mode == RESPONSE_MODE_GENERATE:
            prompt_text = _require_text(action_kwargs, "prompt")
            try:
                reply = await self._call_llm(prompt_text, state)
            except ActionError:
                logger.warning("generate 生成失败，返回兜底话术")
                reply = ACTION_GENERATE_FALLBACK_TEXT
            return ActionResult(messages=[BotMessage(text=reply)])

        raise ActionConfigError(f"不支持的 action_response 模式：{mode}")

    def _render_text(self, text: str, state: DialogueState) -> str:
        """
        用 Jinja2 渲染文案：模板里可访问 slots 与 context。

        - slots：当前业务任务已收集/查到的槽位
        - context：系统过场优先，否则业务任务（对应 system_flows.yml 的 context.xxx）
        """
        template = Template(text)
        return template.render(
            slots=state.active_task.slots if state.active_task is not None else {},
            context=state.active_system_task or state.active_task,
        )

    async def _call_llm(self, prompt_text: str, state: DialogueState, rendered_text: str = "") -> str:
        """
        rephrase / generate 共用：渲染 prompt 模板 -> 调 LLM -> 取纯文本。

        失败统一包装成 ActionError，由 run 决定兜底策略。
        """
        session = state.current_session()
        history = HistoryBuilder.build(session.turns) if session is not None else ""
        pending_turn = state.pending_turn
        user_message = HistoryBuilder.render_user_message(pending_turn.user_message) if pending_turn else ""

        try:
            prompt = PromptTemplate.from_template(prompt_text)
            chain = prompt | self.llm | StrOutputParser()
            reply = await chain.ainvoke(
                {
                    "history": history,
                    "user_message": user_message,
                    "current_response": rendered_text,
                }
            )
        except Exception as exc:
            logger.warning("action_response 调用 LLM 失败", exc_info=True)
            raise ActionError("action_response 调用 LLM 失败") from exc

        return reply.strip()
