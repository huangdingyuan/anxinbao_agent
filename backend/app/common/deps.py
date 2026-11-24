"""FastAPI 公共依赖。

各模块 router 统一从这里导入依赖注入函数，避免重复定义。
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import AsyncSessionFactory
from app.common.utils import decode_access_token
from app.core.exceptions import UnauthorizedError


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """ 为每个 FastAPI 请求创建独立的 AsyncSession，适用于依赖注入。"""
    async with AsyncSessionFactory() as session:
        yield session


def get_current_user_id(
        authorization: Annotated[str | None, Header()] = None,
) -> int:
    """从 Authorization: Bearer <JWT> 解析当前用户 ID；缺失或非法返回 401"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("未登录或缺少认证凭证")
    return decode_access_token(authorization[7:].strip())
