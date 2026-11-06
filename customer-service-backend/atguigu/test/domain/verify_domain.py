"""
Day02 领域模型验证脚本

运行方式（在项目根目录 customer-service-backend 下）：
    uv run python -m atguigu.test.domain.verify_domain

每一节都是一个独立的小实验，只依赖标准库 + pydantic，不连数据库、不调 LLM。
"""

import sys
from pathlib import Path

# 直接运行脚本时，把项目根加入 sys.path（等价于 -m 的效果）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pydantic import ValidationError

from atguigu.domain.contexts import (
    StartedSystemContext,
    SystemContext,
    TaskContext,
    system_context_adapter,
)
from atguigu.domain.messages import BotMessage, FocusedObject, MessageType, UserMessage
from atguigu.domain.state import DialogueState


def title(text: str) -> None:
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)


# ---------------------------------------------------------------- 1
title("1. FocusedObject：序列化与反序列化")

fo = FocusedObject(
    id="A20240315001",
    type="order",
    title="订单 A20240315001",
    attributes={"amount": "8999.00", "status": "待发货"},
)
data = fo.model_dump(mode="json")
back = FocusedObject.model_validate(data)

print("原对象 :", type(fo).__name__, fo)
print("序列化 :", type(data).__name__, data)
print("反序列化:", type(back).__name__, back)
print("两次内容相等吗:", fo == back)


# ---------------------------------------------------------------- 2
title("2. 可变默认值 dict：pydantic 帮你做了隔离")

a = FocusedObject(id="1", type="order")
b = FocusedObject(id="2", type="order")
a.attributes["price"] = 100
print("a.attributes =", a.attributes)
print("b.attributes =", b.attributes, "-> 互不影响，pydantic 每次都会给一个新的空 dict")


# ---------------------------------------------------------------- 3
title("3. MessageType 枚举：传字符串也能自动转换")

msg_text = UserMessage(sender_id="u1", message_id="m1", type="text", text="我要退款")
print("type 字段值 :", msg_text.type, "| 是枚举吗:", isinstance(msg_text.type, MessageType))
print("它的值       :", msg_text.type.value)

msg_obj = UserMessage(
    sender_id="u1",
    message_id="m2",
    type=MessageType.OBJECT,
    object=fo,
)
print("对象消息     :", msg_obj.model_dump(mode="json"))


# ---------------------------------------------------------------- 4
title("4. 必填字段缺失 / 枚举值非法：pydantic 直接拦下")

try:
    UserMessage(sender_id="u1")  # 少了 message_id 和 type
except ValidationError as e:
    print("缺少必填字段 ->", e.errors()[0]["type"], "|", e.errors()[0]["loc"])

try:
    UserMessage(sender_id="u1", message_id="m3", type="voice")  # 枚举里没有 voice
except ValidationError as e:
    print("枚举值非法   ->", e.errors()[0]["type"], "|", e.errors()[0]["loc"])


# ---------------------------------------------------------------- 5
title("5. 五个 SystemContext 子类：默认 flow_id 已经写死")

started = StartedSystemContext(started_flow_id="refund_request", started_flow_name="退款申请")
print("started.flow_id =", started.flow_id, "| 类型:", type(started).__name__)

# 想传错 flow_id 会被 Literal 拦住
try:
    StartedSystemContext(flow_id="system_task_interrupted")
except ValidationError as e:
    print("手写错误的 flow_id ->", e.errors()[0]["type"])


# ---------------------------------------------------------------- 6
title("6. 用父类反序列化 vs 用适配器反序列化（今日最核心的对比）")

raw = {
    "flow_id": "system_task_interrupted",
    "step_id": "acknowledge",
    "interrupted_flow_id": "refund_request",
    "interrupted_flow_name": "退款申请",
    "started_flow_id": "logistics_tracking",
    "started_flow_name": "物流查询",
}

parent_obj = SystemContext.model_validate(raw)
print(
    "父类解析 ->",
    type(parent_obj).__name__,
    "| 有 interrupted_flow_name 吗:",
    hasattr(parent_obj, "interrupted_flow_name"),
)
print("父类解析结果:", parent_obj)

union_obj = system_context_adapter.validate_python(raw)
print(
    "适配器解析 ->",
    type(union_obj).__name__,
    "| 有 interrupted_flow_name 吗:",
    hasattr(union_obj, "interrupted_flow_name"),
)
print("适配器解析结果:", union_obj)

# 适配器还能一次处理"混合类型"的列表
mixed = [
    {"flow_id": "system_task_started", "started_flow_id": "refund_request"},
    {"flow_id": "system_task_canceled", "canceled_flow_id": "refund_request"},
    {
        "flow_id": "system_collect_information",
        "slot_name": "order_number",
        "response": {"text": "请告诉我你的订单号。"},
    },
]
for item in mixed:
    obj = system_context_adapter.validate_python(item)
    print("识别为:", type(obj).__name__)

# 未知 flow_id 会被判别器拒绝
try:
    system_context_adapter.validate_python({"flow_id": "system_unknown"})
except ValidationError as e:
    print("未知 flow_id ->", e.errors()[0]["type"])


# ---------------------------------------------------------------- 7
title("7. DialogueState：一次完整会话的走查")

state = DialogueState(sender_id="u1")

state.start_session()
print("会话已开启, session_id =", state.current_session_id)
print("closed_at =", state.current_session().closed_at)

# --- 第 1 轮：用户说"我要退款"
user_msg = UserMessage(sender_id="u1", message_id="m1", type="text", text="我要退款")
state.begin_turn(user_msg)
print(
    "\nbegin_turn 后, pending_turn 存在吗:",
    state.pending_turn is not None,
    "| 已落盘轮次数:",
    len(state.current_session().turns),
)

# 引擎处理：先插一句过场，再回业务问题（两条机器人消息）
state.pending_turn.bot_messages.append(BotMessage(text="好的，我们先处理退款申请。"))
state.pending_turn.bot_messages.append(BotMessage(text="请告诉我你的订单号。"))

# 业务任务这时也建起来了
state.start_active_task(TaskContext(flow_id="refund_request", step_id="ask_order_number"))
# 系统过场同时存在
state.start_active_system_task(StartedSystemContext(started_flow_id="refund_request", started_flow_name="退款申请"))

print("current_active_task() 返回:", type(state.current_active_task()).__name__, "-> 系统流程优先")

state.end_active_system_task()
print("过场结束后返回:", type(state.current_active_task()).__name__)

state.commit_pending_turn()
print(
    "commit 后, pending_turn 存在吗:",
    state.pending_turn is not None,
    "| 已落盘轮次数:",
    len(state.current_session().turns),
)

# --- 第 2 轮：用户给订单号，槽位写入
state.set_slots({"order_number": "A20240315001"})
print("\n写入槽位后:", state.active_task.slots)

state.remove_slot("order_number")
print("移除槽位后:", state.active_task.slots)
state.set_slots({"order_number": "A20240315001"})


# ---------------------------------------------------------------- 8
title("8. 任务被打断 -> 挂起 -> 精确恢复 -> 取消")

state.interrupted_active_task()
print("打断后 active_task:", state.active_task, "| paused:", [t.flow_id for t in state.paused_tasks])

state.start_active_task(TaskContext(flow_id="logistics_tracking", step_id="ask_order_number"))
print("新任务上线 active_task:", state.active_task.flow_id)

state.interrupted_active_task()
state.start_active_task(
    TaskContext(flow_id="refund_request", step_id="ask_refund_reason", slots={"order_number": "A20240315001"})
)
print("再打断一次 paused:", [t.flow_id for t in state.paused_tasks])

# 用户说"继续刚才的物流" -> 精确恢复
state.resumed_active_task("logistics_tracking")
print("精确恢复后 active:", state.active_task.flow_id, "| paused:", [t.flow_id for t in state.paused_tasks])

# 用户说"继续刚才的" -> 恢复栈顶（LIFO）
state.resumed_active_task(None)
print("默认恢复后 active:", state.active_task.flow_id, "| paused:", [t.flow_id for t in state.paused_tasks])

# 取消当前任务：直接丢弃，不进 paused
state.cancel_active_task()
print("取消后 active:", state.active_task, "| paused:", state.paused_tasks, "| 系统过场:", state.active_system_task)


# ---------------------------------------------------------------- 9
title("9. 关闭会话 + 超时前清理")

state.set_focused_object(fo)
old_id = state.current_session_id
state.close_current_session()
print("关闭后 current_session() 是否为 None:", state.current_session() is None)

closed_session = next(s for s in state.sessions if s.session_id == old_id)
print("那个会话的 closed_at:", closed_session.closed_at, "(已打上时间戳)")
print("current_session_id:", state.current_session_id)

state.reset_runtime_state_for_new_session()
print(
    "清理后: active_task =",
    state.active_task,
    "| paused =",
    state.paused_tasks,
    "| focused =",
    state.focused_object,
    "| 历史会话还保留",
    len(state.sessions),
    "条",
)
