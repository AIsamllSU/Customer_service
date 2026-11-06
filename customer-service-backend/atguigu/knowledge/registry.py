# atguigu/knowledge/registry.py

"""
知识提供者注册表：{provider_id -> provider 实例} 的薄封装。

provider_id 来自代码常量，查不到属于装配错误，直接抛 KeyError 暴露。
"""

from atguigu.knowledge.providers import KnowledgeProvider


class KnowledgeProviderRegistry:
    def __init__(self, providers: list[KnowledgeProvider]) -> None:
        self._providers_by_id = {provider.provider_id: provider for provider in providers}

    def get(self, provider_id: str) -> KnowledgeProvider:
        return self._providers_by_id[provider_id]
