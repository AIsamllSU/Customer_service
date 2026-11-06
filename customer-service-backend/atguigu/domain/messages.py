"""
消息模型 messages.py

一次对话里只有两种消息：
- UserMessage：用户说的话（文本 / 点击的对象）
- BotMessage：机器人说的话（文本 / 返回的对象）
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FocusedObject(BaseModel):
    """
    聚焦对象：用户当前"盯着的那个东西"（订单 / 商品）
    """

    id: str  # 对象的唯一标识（order_id、product_id）
    type: str  # 对象类型（order、product）
    title: str | None = None  # 对象的标题（订单标题或者商品名称）
    attributes: dict[str, Any] = Field(default_factory=dict)  # 对象的额外属性（价格、状态、封面图等）


class MessageType(Enum):
    """
    消息形态：让程序知道这条消息该看 text 还是看 object
    """

    TEXT = "text"  # 文本类型
    OBJECT = "object"  # 对象类型


class UserMessage(BaseModel):
    """
    用户消息
    """

    sender_id: str  # 用户ID（必填）
    message_id: str  # 消息ID（必填）
    type: MessageType  # 消息类型（text 或 object），必填
    text: str | None = None  # 文本消息（用户说的话）
    object: FocusedObject | None = None  # 对象消息（用户点的那张卡片）


class BotMessage(BaseModel):
    """
    机器人消息：只需要关注"回了什么"
    """

    text: str | None = None  # 机器人回复的话
    object: FocusedObject | None = None  # 机器人返回的对象


class ProcessResult(BaseModel):
    """
    引擎一轮处理的返回值：只装"这一轮回复什么"，不装对话状态
    """

    sender_id: str  # 这次回复给哪个用户
    message_id: str  # 本轮消息 id（与请求里的对应）
    messages: list[BotMessage]  # 机器人本轮要回复的消息列表（可能多条）


if __name__ == "__main__":
    attributes = {"price": 100}
    fo = FocusedObject(id="1", type="order", title="订单1", attributes=attributes)

    # 序列化：Python 对象 -> dict（打包）
    data = fo.model_dump(mode="json")
    print(data)
    print(type(data))

    # 反序列化：dict -> Python 对象（拆包）
    fo_obj = FocusedObject.model_validate(data)
    print(fo_obj)
    print(type(fo_obj))
