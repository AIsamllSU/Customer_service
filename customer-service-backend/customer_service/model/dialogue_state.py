# customer_service/model/dialogue_state.py

"""
对话状态的表映射：一个用户一行。

设计取舍：不把 DialogueState 拆成多张表，而是整份状态压成一个 JSON 字符串
塞进 state_json。因为我们的使用方式是"整份读出来、整份写回去"，
从不按状态内部字段做检索，所以一张表两列最简单也够用。
"""

from sqlalchemy import TEXT, String
from sqlalchemy.orm import Mapped, mapped_column

from customer_service.model.base import Base


class DialogueStateRecord(Base):
    __tablename__ = "dialogue_states"

    sender_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # 用户唯一标识
    state_json: Mapped[str] = mapped_column(TEXT, nullable=False)  # 整份状态的 JSON 字符串
