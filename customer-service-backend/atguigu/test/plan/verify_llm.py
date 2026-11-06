# atguigu/test/plan/verify_llm.py

"""
Day05 真实 LLM 验证脚本

验证：
1. 七字段提示词能正常构建
2. jinja2 模板能正常渲染
3. 真实 LLM 能把"我要退款"解析成 TurnPlan（task 轨道 + start_flow）

运行（必须在 customer-service-backend 目录下）：
    uv run python -m atguigu.test.plan.verify_llm
"""

import asyncio
import json
import sys
from pathlib import Path

# 支持直接运行脚本
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from atguigu.domain.messages import MessageType, UserMessage
from atguigu.domain.state import DialogueState
from atguigu.plan.turn_planner import TurnPlanner
from atguigu.task.flow.loader import FlowLoader

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_flows():
    loader = FlowLoader()
    return loader.load_many(
        [
            PROJECT_ROOT / "flow_config" / "user_flows.yml",
            PROJECT_ROOT / "flow_config" / "system_flows.yml",
        ]
    )


def main():
    flows = _load_flows()

    # 造一个"刚开始说话"的状态
    state = DialogueState(sender_id="day05_verify_llm")
    state.start_session()
    state.begin_turn(
        UserMessage(
            sender_id="day05_verify_llm",
            message_id="m1",
            type=MessageType.TEXT,
            text="我要申请退款，订单号是 A001",
        )
    )

    planner = TurnPlanner()

    print("[1] 七字段提示词输入")
    inputs = planner._build_prompt_inputs(state, flows)
    for key, value in inputs.items():
        print(f"\n--- {key} ---")
        print(value if value is not None else "null")

    print("\n[2] 调用真实 LLM 生成 TurnPlan ...")
    plan = asyncio.run(planner.predict(state, flows))
    print("    TurnPlan 对象：", plan)
    print("    JSON：", json.dumps(plan.model_dump(mode="json"), ensure_ascii=False))

    assert plan.task is not None, "期望走 task 轨道"
    assert plan.task.commands[0].command == "start_flow", "期望第一条命令是 start_flow"
    assert plan.task.commands[0].flow == "refund_request", "期望开启 refund_request 流程"

    print("\nDay05 真实 LLM 验证通过 ✅")


if __name__ == "__main__":
    main()
