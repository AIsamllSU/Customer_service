# customer_service/knowledge/intents.py

"""
知识意图注册表

每一类咨询问题 = 一个 KnowledgeIntent。
这张表同时扮演三个角色：
1. 给 LLM 的分类词表（防止它瞎编意图）
2. 校验白名单（意图 id 必须查得到）
3. 路由元数据（provider_ids 决定查哪些知识源，requires_object 决定要不要先有对象）
"""

from pydantic import BaseModel, Field


class KnowledgeIntent(BaseModel):
    id: str
    description: str
    provider_ids: list[str] = Field(default_factory=list)
    requires_object: str | None = None


KNOWLEDGE_INTENTS: dict[str, KnowledgeIntent] = {
    "product_info": KnowledgeIntent(
        id="product_info",
        description="商品信息咨询",
        provider_ids=["api.product"],
        requires_object="product",
    ),
    "order_info": KnowledgeIntent(
        id="order_info",
        description="订单信息咨询",
        provider_ids=["api.order"],
        requires_object="order",
    ),
    "refund_policy": KnowledgeIntent(
        id="refund_policy",
        description="退款政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "return_policy": KnowledgeIntent(
        id="return_policy",
        description="退货政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "shipping_policy": KnowledgeIntent(
        id="shipping_policy",
        description="配送政策咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
    "platform_rule": KnowledgeIntent(
        id="platform_rule",
        description="平台规则咨询",
        provider_ids=["rag.default"],
    ),
    "general_ecommerce_info": KnowledgeIntent(
        id="general_ecommerce_info",
        description="电商通用信息咨询",
        provider_ids=["faq.default", "rag.default"],
    ),
}
