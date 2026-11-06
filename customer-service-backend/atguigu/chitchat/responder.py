# atguigu/chitchat/responder.py

"""
闲聊回复器：用户消息 + 最近对话 -> LLM -> 一句自然回复。
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from atguigu.domain.messages import BotMessage, UserMessage
from atguigu.domain.state import Turn
from atguigu.infrastructure.llm import llm as default_llm
from atguigu.prompts.history_builder import HistoryBuilder
from atguigu.prompts.loader import load_prompt


class ChitChatResponder:
    def __init__(self, llm: BaseChatModel | None = None) -> None:
        # 允许注入假模型，离线测试不联网
        self.llm = llm or default_llm

    async def respond(self, user_message: UserMessage, recent_turns: list[Turn]) -> list[BotMessage]:
        user_message_text = HistoryBuilder.render_user_message(user_message)
        history = HistoryBuilder.build(recent_turns)

        prompt_text = load_prompt("chitchat_respond")
        prompt = PromptTemplate.from_template(template=prompt_text, template_format="jinja2")
        chain = prompt | self.llm | StrOutputParser()

        response = await chain.ainvoke(
            {
                "user_message": user_message_text,
                "history": history,
            }
        )
        return [BotMessage(text=response.strip())]
