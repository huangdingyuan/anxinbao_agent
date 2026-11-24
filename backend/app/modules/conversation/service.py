from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from .repository import ChatThreadRepository
from .models import ChatThread

class ChatThreadService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = ChatThreadRepository(session)

    async def add(self, user_id: int , title: str):
        # 用上下文管理，开启事务，运行完成，自动commit，出现异常，自动rollback
        async with self.session.begin():
            # 创建对象，对象 映射 到数据库 一条数据
            chat_thread = ChatThread(user_id = user_id, title = title)
            # 新增对象，就是插入一条数据
            await self.repository.add(chat_thread)

            return chat_thread

    async def list_by_user(self, user_id: int) -> list[ChatThread]:
        """查询用户的会话列表，按更新时间倒序"""
        result = await self.repository.find_by_user(user_id)
        return list(result)

    async def rename(self, user_id: int, thread_id: UUID, title: str) -> ChatThread:
        """重命名会话，会话不存在或不属于该用户时抛出 NotFoundError"""
        async with self.session.begin():
            chat_thread = await self.repository.get(thread_id, user_id)
            if chat_thread is None:
                raise NotFoundError("会话不存在")
            chat_thread.title = title
            # flush 后回读数据库生成的 updated_at，
            # 避免 commit 后属性过期，响应序列化时触发同步懒加载报错
            await self.session.flush()
            await self.session.refresh(chat_thread)
            return chat_thread

    async def remove(self, user_id: int, thread_id: UUID) -> bool:
        """删除会话，返回是否删除成功"""
        async with self.session.begin():
            chat_thread = await self.repository.get(thread_id, user_id)
            if chat_thread is None:
                return False
            await self.repository.delete(chat_thread)
            return True