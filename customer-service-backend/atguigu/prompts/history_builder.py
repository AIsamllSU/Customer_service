# atguigu/prompts/history_builder.py

"""
历史对话渲染器

LLM 看不懂 Python 对象，所以要把历史 Turn 摊成它读得懂的文本：
- 文本消息：直接取 text
- 对象消息：渲染成 [label=..., id=..., title=..., attributes=...] 这样的描述
"""

from atguigu.domain.constants import OBJECT_TYPE_ORDER
from atguigu.domain.messages import BotMessage, FocusedObject, MessageType, UserMessage
from atguigu.domain.state import Turn


class HistoryBuilder:
    """
    历史记录构建器
    """

    @staticmethod
    def build(turns: list[Turn]) -> str:
        """
        构建历史对话字符串
        """
        msgs: list[str] = []
        for turn in turns:
            # 1. 用户消息
            user_message_str = HistoryBuilder.render_user_message(turn.user_message)
            msgs.append(f"USER: {user_message_str}")

            # 2. 机器人回复（一轮可能有多条）
            for bot_message in turn.bot_messages:
                bot_message_str = HistoryBuilder._render_bot_message(bot_message)
                msgs.append(f"BOT: {bot_message_str}")

        return "\n".join(msgs)

    @staticmethod
    def render_user_message(user_message: UserMessage) -> str:
        """
        渲染用户消息（公开方法：Plan / Clarify 两个模块都会用）
        """
        if user_message.type is MessageType.TEXT:
            return HistoryBuilder._render_text_msg(user_message.text)
        return HistoryBuilder._render_obj_msg(user_message.object)

    @staticmethod
    def _render_bot_message(bot_message: BotMessage) -> str:
        """
        渲染机器人消息
        """
        if bot_message.text:
            return HistoryBuilder._render_text_msg(bot_message.text)
        # 机器人回对象的情况基本走不到，但保留兜底
        return HistoryBuilder._render_obj_msg(bot_message.object)

    @staticmethod
    def _render_text_msg(text: str | None) -> str:
        return (text or "").strip()

    @staticmethod
    def _render_obj_msg(object_msg: FocusedObject | None) -> str:
        """
        渲染对象消息；对象缺失时返回空串，避免 None 崩溃
        """
        if object_msg is None:
            return ""
        label = "订单对象" if object_msg.type == OBJECT_TYPE_ORDER else "商品对象"
        attributes_str = " ".join(f"{key}={value}" for key, value in object_msg.attributes.items())
        return f"[label={label}, id={object_msg.id}, title={object_msg.title}, attributes={attributes_str}]"


if __name__ == "__main__":
    user_msg = UserMessage(
        sender_id="s_1",
        message_id="m_1",
        type=MessageType.TEXT,
        text="今天天气不错",
    )
    bot_msg1 = BotMessage(text="是呀")
    bot_msg2 = BotMessage(
        object=FocusedObject(
            id="r_1",
            type="order",
            title="一个订单",
            attributes={"price": 100, "status": "待支付"},
        )
    )
    turn = Turn(turn_id="t_1", user_message=user_msg, bot_messages=[bot_msg1, bot_msg2])
    print(HistoryBuilder.build([turn]))
