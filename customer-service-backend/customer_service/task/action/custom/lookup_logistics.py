# customer_service/task/action/custom/lookup_logistics.py

"""
查询物流：读 order_number -> 调物流接口 -> 写回单号 / 公司 / 进度。
"""

import logging
from typing import Any

from customer_service.domain.constants import (
    ACTION_LOOKUP_LOGISTICS,
    SLOT_LOGISTICS_COMPANY,
    SLOT_LOGISTICS_STATUS,
    SLOT_ORDER_NUMBER,
    SLOT_TRACKING_NUMBER,
)
from customer_service.domain.state import DialogueState
from customer_service.task.action.base import Action, ActionResult
from customer_service.task.action.custom.shared import fetch_logistics

logger = logging.getLogger(__name__)


class LookupLogisticsAction(Action):
    """
    查询物流进度。
    """

    name = ACTION_LOOKUP_LOGISTICS

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        order_number = state.active_task.slots.get(SLOT_ORDER_NUMBER) if state.active_task is not None else None
        payload = await fetch_logistics(order_number)

        if payload is None:
            logger.info("物流查询失败，写入降级槽位：order_number=%s", order_number)
            return ActionResult(
                slot_updates={
                    SLOT_TRACKING_NUMBER: "未知",
                    SLOT_LOGISTICS_COMPANY: "未知",
                    SLOT_LOGISTICS_STATUS: "暂时无法查到物流信息，请稍后再试。",
                }
            )

        return ActionResult(
            slot_updates={
                SLOT_TRACKING_NUMBER: payload.get("tracking_number") or "未知",
                SLOT_LOGISTICS_COMPANY: payload.get("logistics_company") or "未知",
                SLOT_LOGISTICS_STATUS: payload.get("status_desc") or payload.get("status") or "未知",
            }
        )
