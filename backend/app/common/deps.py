"""FastAPI 公共依赖。

各模块 router 统一从这里导入依赖注入函数，避免重复定义。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import AsyncSessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """ 为每个 FastAPI 请求创建独立的 AsyncSession，适用于依赖注入。"""
    async with AsyncSessionFactory() as session:
        yield session
