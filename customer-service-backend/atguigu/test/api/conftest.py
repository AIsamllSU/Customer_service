# atguigu/test/api/conftest.py

"""
接口层测试的公共夹具。

接口层测试只关心"HTTP 入参出参、依赖注入、落库"，
不应该依赖真实 LLM（慢、花钱、结果不确定）。
所以这里用一个假引擎替换掉真引擎。
"""

import pytest

from atguigu.api.app import app
from atguigu.api.routers import dependencies
from atguigu.domain.messages import BotMessage, ProcessResult


class _StubEngine:
    """
    假引擎：不发网络请求，返回固定回复
    """

    async def process_message(self, dialogue_state, user_message):
        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=[
                BotMessage(text="我是智能客服小谷"),
                BotMessage(text="请输入您的问题"),
            ],
        )


@pytest.fixture(autouse=True)
def stub_dialogue_engine():
    """
    autouse：这个目录下所有用例自动生效
    """
    app.dependency_overrides[dependencies.get_dialogue_engine] = lambda: _StubEngine()
    yield
    app.dependency_overrides.pop(dependencies.get_dialogue_engine, None)
