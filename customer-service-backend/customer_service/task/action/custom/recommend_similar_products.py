# customer_service/task/action/custom/recommend_similar_products.py

"""
推荐相似商品（占位实现）。

与查询类 action 的区别：它直接产出 messages，后面不需要再接 action_response。
"""

import logging
from typing import Any

from customer_service.domain.constants import ACTION_RECOMMEND_SIMILAR_PRODUCTS, SLOT_PRODUCT_ID
from customer_service.domain.messages import BotMessage
from customer_service.domain.state import DialogueState
from customer_service.task.action.base import Action, ActionResult
from customer_service.task.action.custom.shared import fetch_product

logger = logging.getLogger(__name__)


class RecommendSimilarProductsAction(Action):
    """
    相似商品推荐占位：先查商品名让回复更具体，查不到就用"这件商品"兜底。
    """

    name = ACTION_RECOMMEND_SIMILAR_PRODUCTS

    async def run(self, state: DialogueState, action_kwargs: dict[str, Any]) -> ActionResult:
        product_id = state.active_task.slots.get(SLOT_PRODUCT_ID) if state.active_task is not None else None
        label = product_id or "这件商品"

        payload = await fetch_product(product_id)
        if payload:
            label = str(payload.get("title") or "").strip() or label

        text = (
            f'我已经收到你对"{label}"的相似商品推荐需求。'
            "不过当前版本还没有接入正式的推荐系统，稍后可以继续补上这部分能力。"
        )
        logger.info("相似商品推荐占位回复：product_id=%s", product_id)
        return ActionResult(messages=[BotMessage(text=text)])
