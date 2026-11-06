# atguigu/repository/dialogue_state_repository.py

"""
Repository 层：负责 DialogueState 在"内存对象"和"数据库 JSON"之间来回转换。

上层（Service）只调用 load_state / save_state，完全不需要知道底层是
MySQL、SQLite 还是别的存储 —— 这就是 Repository 模式的价值：隔离持久化细节。
"""

import json
import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atguigu.domain.state import DialogueState
from atguigu.model.dialogue_state import DialogueStateRecord

logger = logging.getLogger(__name__)


class DialogueStateRepository:
    """
    持有 AsyncSession，但自己不创建会话 —— 会话由依赖注入传进来。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_state(self, sender_id: str) -> DialogueState:
        """
        读：按 sender_id 查一行；查不到（新用户）就返回一个全新的空状态。
        这样上层永远拿到一个可用的 DialogueState，不用区分新老用户。
        """
        # select * from dialogue_states where sender_id = ?
        sql = select(DialogueStateRecord).where(DialogueStateRecord.sender_id == sender_id)
        result = await self.session.execute(sql)
        state = result.scalar_one_or_none()

        if state:
            try:
                # JSON 字符串 -> dict -> DialogueState 对象
                state_dict = json.loads(state.state_json)
                return DialogueState.model_validate(state_dict)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.exception("对话状态反序列化失败：sender_id=%s", sender_id)
                raise ValueError(f"对话状态数据损坏：sender_id={sender_id}") from exc

        logger.debug("未找到历史状态，创建新状态：sender_id=%s", sender_id)
        return DialogueState(sender_id=sender_id)

    async def save_state(self, dialogue_state: DialogueState) -> None:
        """
        写：一次 upsert（存在则更新，不存在则插入）。

        传统做法是"先查再决定 insert 还是 update"，要两次数据库往返，
        并发下还可能出问题。MySQL 的 on_duplicate_key_update 在主键冲突时
        自动把 INSERT 升级为 UPDATE，一条语句搞定。
        """
        # 整份状态 -> dict -> JSON 字符串
        state_json = json.dumps(dialogue_state.model_dump(mode="json"))

        insert_stmt = insert(DialogueStateRecord).values(
            sender_id=dialogue_state.sender_id,
            state_json=state_json,
        )
        update_stmt = insert_stmt.on_duplicate_key_update(state_json=insert_stmt.inserted.state_json)

        try:
            await self.session.execute(update_stmt)
            await self.session.commit()
            logger.debug("对话状态已保存：sender_id=%s", dialogue_state.sender_id)
        except Exception:
            # 写失败必须回滚，否则事务会一直挂在这个请求的 session 上
            await self.session.rollback()
            logger.exception("对话状态保存失败：sender_id=%s", dialogue_state.sender_id)
            raise
