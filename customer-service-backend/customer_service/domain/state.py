"""
对话状态模型 state.py

DialogueState 是整段对话的"中央仓库"（聚合根）：
- 用户在做什么任务、搁置了哪些任务
- 系统现在在插播什么过场
- 用户聚焦在哪个订单 / 商品
- 历史会话、当前会话、正在处理中的这一轮
"""

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from customer_service.domain.contexts import SystemContext, TaskContext
from customer_service.domain.messages import BotMessage, FocusedObject, UserMessage


class Turn(BaseModel):
    """
    本轮对话：用户说一句 + 机器人回的那几条
    """

    turn_id: str  # 轮次唯一标识，使用 UUID
    user_message: UserMessage  # 这一轮用户说的那一句话
    bot_messages: list[BotMessage]  # 这一轮系统给出的所有回复（可能是多条）


class Session(BaseModel):
    """
    会话：一整段聊天
    """

    session_id: str  # 会话唯一标识，使用 UUID
    started_at: float  # 会话开始的时间戳
    last_activity_at: float  # 最后一次活动的时间戳，用来判断超时
    closed_at: float | None = None  # 会话关闭时间，未关闭时为 None
    turns: list[Turn] = Field(default_factory=list)  # 这个会话里的所有轮次


class DialogueState(BaseModel):
    """
    对话状态聚合根
    """

    sender_id: str  # 用户唯一标识
    active_task: TaskContext | None = None  # 当前活跃的业务任务
    paused_tasks: list[TaskContext] = Field(default_factory=list)  # 被挂起的任务列表（按挂起先后顺序）
    active_system_task: SystemContext | None = None  # 当前执行的系统流程
    focused_object: FocusedObject | None = None  # 用户当前聚焦的订单 / 商品
    sessions: list[Session] = Field(default_factory=list)  # 历史会话列表
    current_session_id: str | None = None  # 当前活跃会话的ID
    pending_turn: Turn | None = None  # 正在处理中的轮次（暂存区）

    # --------------任务相关--------------------------
    def start_active_task(self, active_task: TaskContext) -> None:
        """
        把传进来的 TaskContext 设为活跃任务。
        调用时机：TurnPlanner 判断用户发起了一个新业务任务时。
        """
        self.active_task = active_task

    def end_active_task(self) -> None:
        """
        结束业务任务（流程跑到 end 步骤时）
        """
        self.active_task = None

    def cancel_active_task(self) -> None:
        """
        取消业务任务：活跃任务和系统过场一起清空
        调用时机：用户说"算了不退了"这类取消意图时。
        """
        self.active_task = None
        self.active_system_task = None

    def interrupted_active_task(self) -> None:
        """
        中断活跃任务：把当前活跃任务挪到挂起列表，再清空活跃任务
        调用时机：用户在任务 A 中途切到任务 B 时。
        """
        if self.active_task is None:
            return
        self.paused_tasks.append(self.active_task)
        self.active_task = None

    def resumed_active_task(self, flow_id: str | None = None) -> bool:
        """
        恢复业务任务

        - flow_id 为空：恢复最近挂起的那个（栈顶，LIFO）
        - flow_id 有值：按 flow_id 精确找到并恢复
        - 找不到 / 暂停栈为空：返回 False，不动任何状态

        返回 bool 的原因：CommandProcessor 需要据此判断"到底恢复成功没有"，
        再决定是继续走流程，还是回退（例如先打断当前任务、恢复目标却失败的情况）。

        注意：任务被恢复时 step_id 和 slots 都还在，可以从挂起前的位置接着跑。
        """
        # 0. 没有挂起任务，恢复失败
        if not self.paused_tasks:
            return False

        # 1. 不指名：恢复最近的任务（栈顶，LIFO）
        if not flow_id:
            self.active_task = self.paused_tasks.pop()
            return True

        # 2. 指名：按 flow_id 精确恢复
        for index, task in enumerate(self.paused_tasks):
            if task.flow_id == flow_id:
                self.active_task = task
                del self.paused_tasks[index]
                return True

        # 3. 暂停栈里没有它，恢复失败
        return False

    def start_active_system_task(self, active_system_task: SystemContext) -> None:
        """
        开启系统流程
        调用时机：系统要插播过场白（开始 / 打断 / 取消 / 恢复 / 收集槽位）时。
        """
        self.active_system_task = active_system_task

    def end_active_system_task(self) -> None:
        """
        结束系统流程
        """
        self.active_system_task = None

    def current_active_task(self) -> SystemContext | TaskContext | None:
        """
        返回当前正在执行的任务：系统流程优先，其次业务任务。

        为什么系统流程优先？
        因为系统流程是要插播的过场白，必须先把这句话说完，才能让业务任务继续。
        """
        return self.active_system_task or self.active_task

    # --------------槽位相关--------------------------
    def set_slots(self, slots: dict[str, Any]) -> None:
        """
        设置槽位：把传进来的 dict 合并到当前活跃任务的 slots 里
        """
        self.active_task.slots.update(slots)

    def remove_slot(self, slot_name: str) -> None:
        """
        移除槽位：从当前活跃任务的 slots 里删一个键
        """
        self.active_task.slots.pop(slot_name)

    # -------------- session相关 --------------------------
    def current_session(self) -> Session | None:
        """
        根据 current_session_id 在 sessions 里找出当前会话
        """
        for session in self.sessions:
            if session.session_id == self.current_session_id:
                return session

        return None

    def start_session(self) -> None:
        """
        开启新会话：创建 Session -> 加入 sessions -> 设为当前会话
        """
        if self.current_session() is None:
            now = time.time()
            session_id = str(uuid.uuid4())
            session = Session(
                session_id=session_id,
                started_at=now,
                last_activity_at=now,
            )

            self.sessions.append(session)
            self.current_session_id = session_id

    def close_current_session(self) -> None:
        """
        关闭当前会话：打上关闭时间戳，再把 current_session_id 置空
        """
        # 这里曾写成 is None，导致"没有会话"时直接崩溃，
        # 且"有会话"时永远不关闭，现修正为 is not None
        if self.current_session() is not None:
            self.current_session().closed_at = time.time()
            self.current_session_id = None

    def reset_runtime_state_for_new_session(self) -> None:
        """
        重置运行时状态：会话超时、新会话开始前的"清理工作"

        注意：只清运行时字段（当前任务、挂起任务、系统过场、聚焦对象、暂存轮次），
        不清 sessions —— 历史会话需要保留。
        """
        self.active_task = None
        self.active_system_task = None
        self.paused_tasks = []
        self.focused_object = None
        self.pending_turn = None
        self.current_session_id = None

    # --------------turn相关--------------------------
    def begin_turn(self, message: UserMessage) -> None:
        """
        开始一轮：把用户消息装进新的 Turn，先放 pending_turn（不直接进 session）
        """
        if self.current_session():
            self.pending_turn = Turn(
                turn_id=str(uuid.uuid4()),
                user_message=message,
                bot_messages=[],
            )

    def commit_pending_turn(self) -> None:
        """
        提交一轮：把填好回复的 pending_turn 追加进当前会话，再清空暂存区
        """
        if self.current_session() and self.pending_turn is not None:
            self.current_session().turns.append(self.pending_turn)
            self.pending_turn = None

    # --------------FocusedObject相关--------------------------
    def set_focused_object(self, focused_object: FocusedObject) -> None:
        """
        设置聚焦对象
        调用时机：用户发的不是文本而是一条对象消息（点了订单卡片）时。
        """
        self.focused_object = focused_object
