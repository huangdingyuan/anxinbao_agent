from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.deps import get_session
from .service import UserService
from .schemas import LoginPayload, UserUpdatePayload, UserProfilePayload

router = APIRouter(prefix="/api/v1/users", tags=["用户的接口"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["认证的接口"])


def get_service(session: AsyncSession = Depends(get_session)) -> UserService:
    return UserService(session)


@auth_router.post("/login", response_model=UserProfilePayload)
async def login(
        payload: LoginPayload,
        service: UserService = Depends(get_service),
):
    """用户名+密码登录，成功返回用户资料"""
    return await service.login(payload)


@router.get("/me", response_model=UserProfilePayload)
async def get_my_profile(
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: UserService = Depends(get_service),
):
    """查询当前用户个人资料"""
    return await service.get_profile(user_id)


@router.patch("/me", response_model=UserProfilePayload)
async def update_my_profile(
        payload: UserUpdatePayload,
        user_id: Annotated[int, Header(alias="x-user-id")],
        service: UserService = Depends(get_service),
):
    """编辑当前用户个人资料（昵称/邮箱/手机号）"""
    return await service.update_profile(user_id, payload)
