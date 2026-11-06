# atguigu/knowledge/providers.py

"""
知识提供者：把不同知识来源统一成 retrieve(state) -> list[KnowledgeChunk]。

- API 类：查实时业务数据（商品、订单 + 物流）
- FAQ / RAG 类：当前是占位实现，未来替换成检索库
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from atguigu.conf.config import settings
from atguigu.domain.state import DialogueState
from atguigu.infrastructure import http_client


class KnowledgeChunk(BaseModel):
    """
    一条知识片段：最终会被拼进 knowledge_respond 提示词
    """

    content: str


class KnowledgeProvider(ABC):
    """
    知识提供者基类
    """

    provider_id = ""

    @abstractmethod
    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        """
        按当前对话状态检索知识
        """


class ProductAPIProvider(KnowledgeProvider):
    """
    商品信息：GET /products/{id}
    """

    provider_id = "api.product"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        product_id = self._focused_object_id(state)
        data: dict[str, Any] = await self._get_product_info_by_id(product_id)
        text = json.dumps(data, ensure_ascii=False, indent=2)
        return [KnowledgeChunk(content=f"商品信息:\n{text}")]

    async def _get_product_info_by_id(self, product_id: str) -> dict[str, Any]:
        # 必须通过模块属性取 client：模块级 from ... import http_client 会把
        # 初始化前的 None 拷进本模块，之后 app 初始化也拿不到新客户端。
        response = await http_client.http_client.get(f"{settings.commerce_api_base_url}/products/{product_id}")
        return response.json()["data"]

    @staticmethod
    def _focused_object_id(state: DialogueState) -> str:
        if state.focused_object is None:
            raise ValueError("商品信息检索缺少聚焦商品")
        return state.focused_object.id


class OrderAPIProvider(KnowledgeProvider):
    """
    订单 + 物流信息：两个请求并发，减少等待时间
    """

    provider_id = "api.order"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        order_number = self._focused_object_id(state)

        order_payload, logistics_payload = await asyncio.gather(
            self._fetch_order(order_number),
            self._fetch_logistics(order_number),
        )

        return [
            KnowledgeChunk(
                content="订单与物流信息：\n"
                + json.dumps(
                    {
                        "order_number": order_number,
                        "order": order_payload,
                        "logistics": logistics_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        ]

    async def _fetch_order(self, order_number: str) -> dict[str, Any]:
        response = await http_client.http_client.get(f"{settings.commerce_api_base_url}/orders/{order_number}")
        return response.json()["data"]

    async def _fetch_logistics(self, order_number: str) -> dict[str, Any]:
        response = await http_client.http_client.get(
            f"{settings.commerce_api_base_url}/orders/{order_number}/logistics"
        )
        return response.json().get("data", {})

    @staticmethod
    def _focused_object_id(state: DialogueState) -> str:
        if state.focused_object is None:
            raise ValueError("订单信息检索缺少聚焦订单")
        return state.focused_object.id


class FAQProvider(KnowledgeProvider):
    """
    FAQ 占位：接口契约先定下来，后续替换成 ElasticSearch
    """

    provider_id = "faq.default"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        return [KnowledgeChunk(content="FAQ：未检索到相关问题")]


class RAGProvider(KnowledgeProvider):
    """
    RAG 占位：后续替换成向量数据库
    """

    provider_id = "rag.default"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        return [KnowledgeChunk(content="RAG：未检索到相关信息")]
