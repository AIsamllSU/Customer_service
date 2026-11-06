# customer_service/responder/clarify_responder.py

"""
ClarifyResponder：把"原因码"变成一句自然的追问

两段式：
1. 规则兜底：按 reason 写死一句基础话术，保证永远有话说
2. LLM 润色：把基础话术 + 上下文交给 LLM 改写得更自然
"""

import json
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from customer_service.domain.constants import (
    HISTORY_WINDOW_TURNS,
    OBJECT_TYPE_ORDER,
    OBJECT_TYPE_PRODUCT,
)
from customer_service.domain.messages import BotMessage
from customer_service.domain.state import DialogueState
from customer_service.infrastructure.llm import llm as default_llm
from customer_service.plan.models import ClarifyReason
from customer_service.prompts.history_builder import HistoryBuilder
from customer_service.prompts.loader import load_prompt

logger = logging.getLogger(__name__)


class ClarifyResponder:
    def __init__(self, llm: BaseChatModel | None = None) -> None:
        # 允许注入假模型，测试时不必联网
        self.llm = llm or default_llm

    def build_clarify_message(self, reason: ClarifyReason, state: DialogueState) -> str:
        """
        第一步：规则兜底话术
        """
        if reason is ClarifyReason.MULTIPLE_TRACKS:
            return "你这次同时提到了多个方向。我们先处理一个，你想先办业务还是先咨询信息呢？"

        if reason is ClarifyReason.MISSING_FOCUSED_OBJECT:
            return "请先发送你想咨询的对象，我再继续帮你看。"

        if reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT:
            return "你是想了解商品信息、订单信息，还是售后配送规则呢？"

        if reason is ClarifyReason.MISSING_TRACK:
            return "你是想先处理业务问题，还是先咨询信息呢？"

        if reason is ClarifyReason.MISSING_TASK_COMMANDS:
            return "你这次是想办理什么业务呢？比如查订单、查物流，或者申请退款。"

        if reason is ClarifyReason.OBJECT_REQUIRES_INTENT:
            focused_object = state.focused_object
            if focused_object is not None and focused_object.type == OBJECT_TYPE_ORDER:
                return "我已经收到这个订单了。你想查订单状态、查物流，还是申请退款呢？"
            if focused_object is not None and focused_object.type == OBJECT_TYPE_PRODUCT:
                return "我已经收到这个商品了。你想了解它的商品信息、发货情况，还是售后相关问题呢？"

        return "我还需要再确认一下你的意思，你可以换个更具体的说法告诉我。"

    async def respond(self, state: DialogueState, reason: ClarifyReason) -> list[BotMessage]:
        """
        第二步：LLM 润色后返回
        """
        message = state.pending_turn.user_message
        clarify_message = self.build_clarify_message(reason=reason, state=state)

        user_message = HistoryBuilder.render_user_message(message)
        session = state.current_session()
        history = HistoryBuilder.build(session.turns[-HISTORY_WINDOW_TURNS:] if session is not None else [])
        focused_object = (
            json.dumps(state.focused_object.model_dump(mode="json"), ensure_ascii=False)
            if state.focused_object is not None
            else None
        )

        prompt_text = load_prompt("clarify_respond")
        prompt = PromptTemplate.from_template(template=prompt_text, template_format="jinja2")
        chain = prompt | self.llm | StrOutputParser()

        try:
            rewritten = await chain.ainvoke(
                {
                    "reason": reason.value,
                    "clarify_message": clarify_message,
                    "focused_object": focused_object,
                    "history": history,
                    "user_message": user_message,
                }
            )
        except Exception:
            # LLM 润色失败也不能让用户收不到话：退回规则兜底话术
            logger.warning("澄清话术润色失败，使用规则兜底话术", exc_info=True)
            rewritten = clarify_message

        return [BotMessage(text=rewritten.strip())]
