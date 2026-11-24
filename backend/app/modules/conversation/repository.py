from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatThread


class ChatThreadRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, chat_thread: ChatThread):
        self.session.add(chat_thread)

    async def find_by_user(self, user_id: int) -> Sequence[ChatThread]:
        """查询指定用户的会话列表，按更新时间倒序"""
        result = await self.session.execute(
            select(ChatThread)
            .where(ChatThread.user_id == user_id)
            .order_by(ChatThread.updated_at.desc())
        )
        return result.scalars().all()

    async def get(self, thread_id: UUID, user_id: int) -> ChatThread | None:
        """按主键+用户查询会话，保证只能操作自己的会话"""
        result = await self.session.execute(
            select(ChatThread).where(
                ChatThread.id == thread_id,
                ChatThread.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, chat_thread: ChatThread) -> None:
        """删除会话"""
        await self.session.delete(chat_thread)