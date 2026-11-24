from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ChatMessage


class ChatMessageRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, chat_message: ChatMessage):
        self.session.add(chat_message)

    async def find_by_thread(self, thread_id: UUID) -> Sequence[ChatMessage]:
        """查询会话的全部消息，按创建时间正序"""
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return result.scalars().all()
