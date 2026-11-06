# customer_service/task/action/custom/shared.py

"""
自定义 action 共用的电商接口工具。

设计要点：
- 复用进程级 http_client（连接池），不在每次请求里新建
- 所有异常都在这里吞掉并返回 None，交给 action 写降级槽位，保证流程不崩
- 只读取 {"data": {...}} 里的 data，统一剥壳
"""

import logging
from typing import Any
from urllib.parse import quote

from customer_service.conf.config import settings
from customer_service.infrastructure import http_client as http_client_module

logger = logging.getLogger(__name__)


def _base_url() -> str:
    """
    电商中台地址，去掉末尾斜杠，避免拼出 //orders。
    """
    return settings.commerce_api_base_url.rstrip("/")


def _extract_data(result: Any) -> dict[str, Any] | None:
    """
    统一剥出 {"data": {...}} 里的 data；结构不对就返回 None。
    """
    data = result.get("data") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else None


async def _fetch_json(path: str) -> dict[str, Any] | None:
    """
    发起一次 GET 并返回 data；任何异常都记录日志后降级为 None。

    注意：必须通过模块访问 http_client，不能在导入时 `from ... import http_client`。
    后者会把启动前的 None 固化成局部变量，即使 lifespan 初始化了客户端也永远用不到。
    """
    client = http_client_module.http_client
    if client is None:
        logger.warning("HTTP 客户端尚未初始化，跳过电商接口调用：%s", path)
        return None

    try:
        response = await client.get(f"{_base_url()}{path}")
        response.raise_for_status()
        return _extract_data(response.json())
    except Exception:
        logger.warning("电商接口调用失败：%s", path, exc_info=True)
        return None


async def fetch_order(order_id: str | None) -> dict[str, Any] | None:
    """
    查询订单详情。
    """
    if not order_id:
        logger.info("缺少订单号，跳过订单接口调用")
        return None
    return await _fetch_json(f"/orders/{quote(str(order_id), safe='')}")


async def fetch_logistics(order_id: str | None) -> dict[str, Any] | None:
    """
    查询订单物流。
    """
    if not order_id:
        logger.info("缺少订单号，跳过物流接口调用")
        return None
    return await _fetch_json(f"/orders/{quote(str(order_id), safe='')}/logistics")


async def fetch_product(product_id: str | None) -> dict[str, Any] | None:
    """
    查询商品详情。
    """
    if not product_id:
        logger.info("缺少商品 ID，跳过商品接口调用")
        return None
    return await _fetch_json(f"/products/{quote(str(product_id), safe='')}")


def _build_order_summary(payload: dict[str, Any]) -> str:
    """
    把订单数据拼成一句摘要：金额 + 前两个商品标题。
    """
    parts: list[str] = []

    if payload.get("amount"):
        parts.append(f"订单金额 ¥{payload['amount']}")

    items = payload.get("items") or []
    if items:
        titles = [str(item.get("title_snapshot") or item.get("title") or "").strip() for item in items[:2]]
        titles = [title for title in titles if title]
        if titles:
            parts.append("商品：" + "、".join(titles))

    return "。".join(parts) + "。" if parts else ""
