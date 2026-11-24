from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.common.deps import get_session
from .schemas import *
from .service import ChatThreadService

router = APIRouter(prefix="/api/v1/chat-threads", tags=["会话管理的接口"])


def get_service(session: AsyncSession = Depends(get_session)):
    return ChatThreadService(session)


@router.post("", response_model=ChatThreadResponse)
async def create_chat_thread(
        request: ChatThreadCreate,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatThreadService = Depends(get_service),
):
    """创建会话"""

    return await service.add(user_id, request.title)


@router.get("", response_model=list[ChatThreadResponse])
async def list_chat_threads(
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatThreadService = Depends(get_service),
):
    """查询当前用户的会话列表，按更新时间倒序"""

    return await service.list_by_user(user_id)


@router.patch("/{thread_id}", response_model=ChatThreadResponse)
async def rename_chat_thread(
        thread_id: UUID,
        request: ChatThreadUpdate,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatThreadService = Depends(get_service),
):
    """重命名会话，不存在或越权时由全局异常处理器返回 404"""

    return await service.rename(user_id, thread_id, request.title)


@router.delete("/{thread_id}", status_code=204)
async def delete_chat_thread(
        thread_id: UUID,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: ChatThreadService = Depends(get_service),
):
    """删除会话，不存在或越权时由全局异常处理器返回 404"""

    deleted = await service.remove(user_id, thread_id)
    if not deleted:
        raise NotFoundError("会话不存在")