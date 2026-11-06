# atguigu/knowledge/handler.py

"""
知识轨道入口：意图 -> 知识来源 -> 知识片段 -> 回复。

三步：
1. _get_provider_ids_by_intents：意图映射到 provider_id
2. 逐个 provider.retrieve(state)：检索知识
3. knowledge_responder.respond(...)：用知识生成回复
"""

from atguigu.domain.messages import BotMessage
from atguigu.domain.state import DialogueState
from atguigu.knowledge.intents import KnowledgeIntent
from atguigu.knowledge.providers import KnowledgeChunk
from atguigu.knowledge.registry import KnowledgeProviderRegistry
from atguigu.knowledge.responder import KnowledgeResponder


class KnowledgeHandler:
    def __init__(
        self,
        knowledge_intents: dict[str, KnowledgeIntent],
        provider_registry: KnowledgeProviderRegistry,
        knowledge_responder: KnowledgeResponder,
    ) -> None:
        self.knowledge_intents = knowledge_intents
        self.provider_registry = provider_registry
        self.knowledge_responder = knowledge_responder

    async def handle(self, intents: list[str], state: DialogueState) -> list[BotMessage]:
        pending_turn = state.pending_turn
        if pending_turn is None:
            raise ValueError("当前没有待处理的用户消息")

        # 1. 意图 -> provider_id
        provider_ids = self._get_provider_ids_by_intents(intents)

        # 2. 逐个 provider 检索
        chunks: list[KnowledgeChunk] = []
        for provider_id in provider_ids:
            chunks.extend(await self.provider_registry.get(provider_id).retrieve(state))

        # 3. 知识 + 上下文 -> 回复
        recent_turns = state.current_session().turns if state.current_session() is not None else []
        return await self.knowledge_responder.respond(
            user_message=pending_turn.user_message,
            recent_turns=recent_turns,
            chunks=chunks,
        )

    def _get_provider_ids_by_intents(self, intents: list[str]) -> list[str]:
        provider_ids: list[str] = []
        for intent in intents:
            provider_ids.extend(self.knowledge_intents[intent].provider_ids)
        # 同一 provider 被多个意图命中时只查一次
        return list(set(provider_ids))
