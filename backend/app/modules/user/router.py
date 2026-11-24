from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.deps import get_current_user_id, get_session
from app.common.utils import create_access_token
from .service import UserService
from .schemas import LoginPayload, LoginResult, UserUpdatePayload, UserProfilePayload

router = APIRouter(prefix="/api/v1/users", tags=["用户的接口"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["认证的接口"])


def get_service(session: AsyncSession = Depends(get_session)) -> UserService:
    return UserService(session)


@auth_router.post("/login", response_model=LoginResult)
async def login(
        payload: LoginPayload,
        service: UserService = Depends(get_service),
):
    """用户名+密码登录，成功签发 JWT 访问令牌并返回用户资料"""
    profile = await service.login(payload)
    return LoginResult(access_token=create_access_token(profile.id), user=profile)


@router.get("/me", response_model=UserProfilePayload)
async def get_my_profile(
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: UserService = Depends(get_service),
):
    """查询当前用户个人资料"""
    return await service.get_profile(user_id)


@router.patch("/me", response_model=UserProfilePayload)
async def update_my_profile(
        payload: UserUpdatePayload,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: UserService = Depends(get_service),
):
    """编辑当前用户个人资料（昵称/邮箱/手机号）"""
    return await service.update_profile(user_id, payload)
