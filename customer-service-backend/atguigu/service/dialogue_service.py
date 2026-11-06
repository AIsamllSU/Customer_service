# atguigu/service/dialogue_service.py

"""
Service 层：编排一次完整的对话处理。

三步编排：① 加载状态 → ② 引擎处理 → ③ 保存状态
关键设计：I/O 集中在两端（Service），计算集中在中间（Engine）。
引擎是纯计算、无副作用的：它就地修改传进去的 state，不碰数据库。
"""

import logging

from atguigu.domain.messages import ProcessResult, UserMessage
from atguigu.domain.state import DialogueState
from atguigu.engine.dialogue_engine import DialogueEngine
from atguigu.repository.dialogue_state_repository import DialogueStateRepository

logger = logging.getLogger(__name__)


class DialogueService:
    """
    处理对话的业务类
    """

    def __init__(
        self,
        dialogue_engine: DialogueEngine,
        dialogue_state_repository: DialogueStateRepository,
    ) -> None:
        self.dialogue_engine = dialogue_engine
        self.dialogue_state_repository = dialogue_state_repository

    async def process_message(self, user_message: UserMessage) -> ProcessResult:
        """
        处理用户消息
        """
        logger.info("加载对话状态：sender_id=%s", user_message.sender_id)
        # 1. 加载：按 sender_id 从数据库读出这个用户的对话状态
        dialogue_state: DialogueState = await self.dialogue_state_repository.load_state(user_message.sender_id)

        # 2. 处理：交给引擎，引擎就地修改 dialogue_state，并返回本轮回复
        process_result: ProcessResult = await self.dialogue_engine.process_message(dialogue_state, user_message)

        # 3. 保存：把被引擎改过的同一份状态写回数据库
        await self.dialogue_state_repository.save_state(dialogue_state)

        # 4. 返回本轮处理结果
        logger.info(
            "对话处理完成：sender_id=%s message_id=%s 回复条数=%d",
            user_message.sender_id,
            user_message.message_id,
            len(process_result.messages),
        )
        return process_result
