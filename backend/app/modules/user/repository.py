from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


class UserRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def find_by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username).limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_email(self, email: str, exclude_user_id: int) -> User | None:
        """查询 email 是否已被其他用户占用"""
        result = await self.session.execute(
            select(User).where(User.email == email, User.id != exclude_user_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def save(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
