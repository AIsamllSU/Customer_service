"""
Day03 验证脚本：流程数据模型与加载

运行（在 customer-service-backend 根目录）：
    uv run python -m atguigu.test.flow.verify_flow

共 9 个实验，只依赖标准库 + pydantic + pyyaml，不连数据库、不调 LLM。
"""

import sys
import tempfile
from pathlib import Path

# 直接运行脚本时，把项目根加入 sys.path（等价于 -m 的效果）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import yaml

from atguigu.task.flow.loader import FlowLoader
from atguigu.task.flow.steps import (
    CollectFlowStep,
    FlowStep,
)

BASE_PATH = Path(__file__).parents[3]
USER_FLOW_PATH = BASE_PATH / "flow_config" / "user_flows.yml"
SYSTEM_FLOW_PATH = BASE_PATH / "flow_config" / "system_flows.yml"


def title(text: str) -> None:
    print("\n" + "=" * 62)
    print(text)
    print("=" * 62)


# ---------------------------------------------------------------- 1
title("1. YAML -> dict：缩进变成嵌套，'-' 变成列表")

with open(USER_FLOW_PATH, encoding="utf-8") as f:
    raw = yaml.safe_load(f)

print("顶层键:", list(raw.keys()))
print("slots 的键:", list(raw.get("slots", {}).keys())[:3], "...")
refund_steps = raw["flows"]["refund_request"]["steps"]
print("refund_request 的步骤数:", len(refund_steps))
print("第一个步骤:", refund_steps[0])
print("第三个步骤:", refund_steps[2])
print("类型确认:", type(raw).__name__, type(refund_steps).__name__)


# ---------------------------------------------------------------- 2
title("2. build_links：三种 next 写法翻译成三种边")

print("字符串 next:")
print(" ", FlowStep.build_links("ask_order_number"))

print("if / else 列表:")
links = FlowStep.build_links(
    [
        {"if": "slots.get('product_id')", "then": "respond"},
        {"if": "context.get('reason') == 'not_supported'", "then": "not_supported"},
        {"else": "ask_product_id"},
    ]
)
for link in links:
    print(" ", type(link).__name__, link)


# ---------------------------------------------------------------- 3
title("3. from_dict：按 type 造出正确的子类")

step_dicts = [
    {"id": "start", "type": "start", "next": "respond"},
    {"id": "respond", "type": "action", "action": "action_response", "args": {"text": "你好"}, "next": "end"},
    {
        "id": "ask",
        "type": "collect",
        "slot_name": "order_number",
        "response": {"text": "请告诉我你的订单号。"},
        "next": "end",
    },
    {"id": "end", "type": "end", "next": []},
]

for data in step_dicts:
    step = FlowStep.from_dict(data)
    print(
        f"type={data['type']:<8} -> {type(step).__name__:<16} "
        f"枚举={step.type} next={type(step.next[0]).__name__ if step.next else '[]'}"
    )

# 子类的专属字段
action_step = FlowStep.from_dict(step_dicts[1])
print("ActionFlowStep.action =", action_step.action, "| args =", action_step.args)

collect_step = FlowStep.from_dict(step_dicts[2])
print(
    "CollectFlowStep.slot_name =",
    collect_step.slot_name,
    "| response.text =",
    collect_step.response.text,
    "| response.model =",
    collect_step.response.model,
)


# ---------------------------------------------------------------- 4
title("4. 变量引用字符串型 args（system_collect_information）")

flows_list = FlowLoader().load_many([USER_FLOW_PATH, SYSTEM_FLOW_PATH])
collect_flow = flows_list.get_flow_by_id("system_collect_information")
ask_step = collect_flow.get_step_by_id("ask")

print("ask 步骤类型:", type(ask_step).__name__)
print("args =", repr(ask_step.args), "| 类型:", type(ask_step.args).__name__)
print("说明：这里 args 整体引用 context.response，所以允许 str")


# ---------------------------------------------------------------- 5
title("5. Flow 的两个查找方法")

refund = flows_list.get_flow_by_id("refund_request")
print("flow.name:", refund.name)
print("start_step:", type(refund.start_step()).__name__, refund.start_step().id)
print("get_step_by_id('ask_refund_reason'):", type(refund.get_step_by_id("ask_refund_reason")).__name__)
print("get_step_by_id('不存在'):", refund.get_step_by_id("不存在"))
print("get_flow_by_id('nope'):", flows_list.get_flow_by_id("nope"))


# ---------------------------------------------------------------- 6
title("6. 加载结果总览 + 流程级槽位")

print(f"流程总数: {len(flows_list.flows)} | 全局槽位总数: {len(flows_list.slots)}")
print("全局槽位:", sorted(flows_list.slots))

for flow in flows_list.flows:
    print(f"- {flow.id:<32} steps={len(flow.steps):<2} slots={[s.name for s in flow.slots]}")

print("\n重点核对 refund_request:")
print("  步骤序列:", [s.id for s in refund.steps])
print("  使用槽位:", [s.name for s in refund.slots])
print("  槽位定义:", refund.slots[0])


# ---------------------------------------------------------------- 7
title("7. 同一流程重复 collect 同一槽位：flow.slots 只留一份")

yaml_text = """
slots:
  order_number:
    type: text
    label: 订单号

flows:
  demo_flow:
    name: 演示流程
    steps:
      - id: start
        type: start
        next: ask1
      - id: ask1
        type: collect
        slot_name: order_number
        response:
          text: "第一次问订单号"
        next: ask2
      - id: ask2
        type: collect
        slot_name: order_number
        response:
          text: "再问一次订单号"
        next: end
      - id: end
        type: end
        next: []
"""

with tempfile.TemporaryDirectory() as tmp_dir:
    demo_path = Path(tmp_dir) / "demo.yml"
    demo_path.write_text(yaml_text, encoding="utf-8")

    demo_flows = FlowLoader().load(demo_path)
    demo = demo_flows.get_flow_by_id("demo_flow")

    collects = [s for s in demo.steps if isinstance(s, CollectFlowStep)]
    print("collect 步骤数:", len(collects), "->", [s.id for s in collects])
    print("flow.slots 数量:", len(demo.slots), "->", [s.name for s in demo.slots])


# ---------------------------------------------------------------- 8
title("8. 跨文件重复槽位：加载期直接失败（fail fast）")

dup_yaml = """
slots:
  order_number:
    type: text
    label: 重复的订单号
flows: {}
"""

with tempfile.TemporaryDirectory() as tmp_dir:
    dup_path = Path(tmp_dir) / "dup.yml"
    dup_path.write_text(dup_yaml, encoding="utf-8")
    try:
        FlowLoader().load_many([USER_FLOW_PATH, dup_path])
    except ValueError as e:
        print("捕获到 ValueError:", e)


# ---------------------------------------------------------------- 9
title("9. 图完整性检查：每个 next 目标都必须真实存在")

problems = []
for flow in flows_list.flows:
    step_ids = {step.id for step in flow.steps}
    if flow.start_step() is None:
        problems.append(f"{flow.id}: 没有 start 步骤")
    for step in flow.steps:
        for link in step.next:
            if link.target not in step_ids:
                problems.append(f"{flow.id}/{step.id}: next -> {link.target} 不存在")

print("问题数量:", len(problems))
for p in problems:
    print(" -", p)

# 附加：统计边的类型
edge_counts = {"StaticLink": 0, "ConditionalLink": 0, "FallbackLink": 0}
for flow in flows_list.flows:
    for step in flow.steps:
        for link in step.next:
            edge_counts[type(link).__name__] += 1
print("边的类型统计:", edge_counts)
