# atguigu/task/action/custom/lookup_order_status.py

"""
查询订单状态：读 order_number -> 调订单接口 -> 写回 order_status / order_summary。

只写槽位、不发消息——"把槽位拼成话"是 action_response 的职责。
"""

import logging
from typing import Any

from atguigu.domain.constants import (
    ACTION_LOOKUP_ORDER_STATUS,
    SLOT_ORDER_NUMBER,
    SLOT_ORDER_STATUS,
    SLOT_ORDER_SUMMARY,
)
from atguigu.domain.state import DialogueState
from atguigu.task.action.base import Action, ActionResult
from atguigu.task.action.custom.shared import _build_order_summary, fetch_order

logger = logging.getLogger(__name__)


class LookupOrderStatusAction(Action):
    """
    查询订单状态。
    """

    name = ACTION_LOOKUP_ORDER_STATUS

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        order_number = state.active_task.slots.get(SLOT_ORDER_NUMBER) if state.active_task is not None else None
        payload = await fetch_order(order_number)

        if payload is None:
            logger.info("订单状态查询失败，写入降级槽位：order_number=%s", order_number)
            return ActionResult(
                slot_updates={
                    SLOT_ORDER_STATUS: "查询失败",
                    SLOT_ORDER_SUMMARY: "暂时无法查到该订单信息，请稍后再试。",
                }
            )

        return ActionResult(
            slot_updates={
                SLOT_ORDER_STATUS: payload.get("status_desc") or payload.get("status") or "未知",
                SLOT_ORDER_SUMMARY: _build_order_summary(payload),
            }
        )
