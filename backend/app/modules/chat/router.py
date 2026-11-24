from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, NotFoundError
from app.common.deps import get_session
from .schemas import ChatAskRequest, ChatFrontendAsk, ChatHistoryResponse, ChatMessageResponse
from .service import ChatService

router = APIRouter(prefix="/api/v1/chat-threads", tags=["智能问答的接口"])

# 前端契约路由（不带 prefix）
frontend_router = APIRouter(tags=["智能问答的接口"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，保证流式即时下发
}


def get_service(session: AsyncSession = Depends(get_session)):
    return ChatService(session)


@frontend_router.post("/api/v1/chat")
async def chat(
        request: ChatFrontendAsk,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatService = Depends(get_service),
):
    """前端流式问答（SSE）：
    - message 事件：逐段推送回答内容（data 为 JSON 字符串）
    - additional_info 事件：回答结束后下发参考产品等信息
    - interrupt 事件：推荐多款产品时下发保障方案，等待用户确认
    - thread_id 为空时自动创建会话
    """
    if request.decision is not None:
        if request.thread_id is None:
            raise BizError("缺少会话标识")
        stream = await service.handle_decision(user_id, request.thread_id, request.decision)
        return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)
    if not request.message or not request.message.strip():
        raise BizError("消息内容不能为空")

    content = request.message.strip()
    thread_id = await service.resolve_thread(user_id, request.thread_id, content)
    history = await service.prepare_ask(user_id, thread_id, content)

    return StreamingResponse(
        service.build_frontend_stream(thread_id, history, content),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/{thread_id}/messages", response_model=ChatHistoryResponse)
async def list_chat_messages(
        thread_id: UUID,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatService = Depends(get_service),
):
    """查询会话的消息历史，按时间正序（interrupt 为待确认的方案，若有）"""

    messages = await service.list_messages(user_id, thread_id)
    interrupt = await service.get_pending_interrupt(user_id, thread_id)
    return ChatHistoryResponse(
        thread_id=thread_id,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
        interrupt=interrupt,
    )


@router.post("/{thread_id}/chat")
async def ask_chat_thread(
        thread_id: UUID,
        request: ChatAskRequest,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatService = Depends(get_service),
):
    """内部流式问答（SSE）：
    - delta 事件：逐段推送回答内容
    - references 事件：回答结束后下发参考来源
    - done / error 事件：结束或失败
    """
    # 先校验会话归属并保存用户消息（此时抛错仍能返回正常的 JSON 错误响应）
    history = await service.prepare_ask(user_id, thread_id, request.content)

    return StreamingResponse(
        service.build_stream(thread_id, history, request.content),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
