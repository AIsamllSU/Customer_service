# atguigu/api/routers/chat_router.py

"""
chat 路由：Web 层的核心是"翻译"。

两次自动转换（FastAPI 负责 JSON <-> schema）
两次手动翻译（我们负责 schema <-> domain）
中间夹一次 Service 调用。
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from atguigu.api.routers.dependencies import get_dialogue_service
from atguigu.api.schemas import (
    ChatBotMessage,
    ChatObject,
    ChatRequest,
    ChatResponse,
    HistoryMessage,
    HistoryResponse,
)
from atguigu.domain.messages import FocusedObject, MessageType, ProcessResult, UserMessage
from atguigu.plan.errors import TurnPlanningError
from atguigu.service.dialogue_service import DialogueService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(
    chat_request: ChatRequest,
    # 依赖注入：框架帮我们把 Service 准备好传进来
    dialogue_service: DialogueService = Depends(get_dialogue_service),
) -> ChatResponse:
    # 1. 接口模型 -> 领域模型
    user_message = _build_user_message(chat_request)
    logger.info(
        "收到对话请求：sender_id=%s message_id=%s type=%s",
        user_message.sender_id,
        user_message.message_id,
        user_message.type.value,
    )

    # 2. 业务处理（边界处兜底：区分"模型不可用"和"程序异常"，不把堆栈暴露给客户端）
    try:
        process_result: ProcessResult = await dialogue_service.process_message(user_message)
    except TurnPlanningError as exc:
        logger.exception("LLM 规划失败：sender_id=%s message_id=%s", user_message.sender_id, user_message.message_id)
        raise HTTPException(status_code=503, detail="AI 服务暂时不可用，请稍后重试") from exc
    except Exception as exc:
        logger.exception("对话处理异常：sender_id=%s message_id=%s", user_message.sender_id, user_message.message_id)
        raise HTTPException(status_code=500, detail="服务内部错误，请稍后重试") from exc

    # 3. 领域模型 -> 接口模型
    return _build_chat_response(process_result)


def _build_user_message(chat_request: ChatRequest) -> UserMessage:
    """
    schema -> domain
    """
    return UserMessage(
        sender_id=chat_request.sender_id,
        # 客户端没传 message_id 就生成一个，保证每条消息都有 id
        message_id=chat_request.message_id if chat_request.message_id else str(uuid.uuid4()),
        # 有文本就是 TEXT，否则当 OBJECT
        type=MessageType.TEXT if chat_request.text else MessageType.OBJECT,
        text=chat_request.text,
        object=FocusedObject(
            id=chat_request.object.id,
            type=chat_request.object.type,
            title=chat_request.object.title,
            attributes=chat_request.object.attributes,
        )
        if chat_request.object
        else None,
    )


def _build_chat_response(process_result: ProcessResult) -> ChatResponse:
    """
    domain -> schema
    """
    return ChatResponse(
        sender_id=process_result.sender_id,
        message_id=process_result.message_id,
        messages=[
            ChatBotMessage(
                text=bot_msg.text,
                object=ChatObject(
                    type=bot_msg.object.type,
                    id=bot_msg.object.id,
                    title=bot_msg.object.title,
                    attributes=bot_msg.object.attributes,
                )
                if bot_msg.object
                else None,
            )
            for bot_msg in process_result.messages
        ],
    )


@router.get("/api/chat/history", response_model=HistoryResponse)
async def history(sender_id: str) -> HistoryResponse:
    """
    历史接口：本节先用写死的假数据占位，保证前端联调时结构正确。
    真正实现要从 DialogueState.sessions 里取出历史 Turn 再翻译。
    """
    return HistoryResponse(
        sender_id=sender_id,
        messages=[
            HistoryMessage(role="user", text="你好"),
            HistoryMessage(role="bot", text="我不好"),
        ],
    )
