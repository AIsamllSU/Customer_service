# atguigu/chitchat/handler.py

"""
闲聊轨道入口：只负责从 state 取原料，真正的回复交给 responder。
"""

from atguigu.chitchat.responder import ChitChatResponder
from atguigu.domain.messages import BotMessage
from atguigu.domain.state import DialogueState


class ChitChatHandler:
    def __init__(self, responder: ChitChatResponder) -> None:
        self.responder = responder

    async def handle(self, state: DialogueState) -> list[BotMessage]:
        pending_turn = state.pending_turn
        if pending_turn is None:
            raise ValueError("当前没有待处理的用户消息")

        recent_turns = state.current_session().turns if state.current_session() is not None else []
        return await self.responder.respond(
            user_message=pending_turn.user_message,
            recent_turns=recent_turns,
        )
