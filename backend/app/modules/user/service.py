"""用户服务"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils import verify_password
from app.core.exceptions import BizError, NotFoundError, UnauthorizedError
from .models import User
from .repository import UserRepository
from .schemas import LoginPayload, UserUpdatePayload, UserProfilePayload


class UserService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = UserRepository(session)

    async def login(self, payload: LoginPayload) -> UserProfilePayload:
        """用户名+密码登录，bcrypt 校验 password_hash"""
        user = await self.repository.find_by_username(payload.username)
        # 统一提示语，避免暴露用户是否存在
        if user is None:
            raise UnauthorizedError("用户名或密码错误")
        if user.status != "active":
            raise BizError("账号已禁用，请联系管理员")
        if not verify_password(payload.password, user.password_hash):
            raise UnauthorizedError("用户名或密码错误")
        return UserProfilePayload.model_validate(user)

    async def get_profile(self, user_id: int) -> UserProfilePayload:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        return UserProfilePayload.model_validate(user)

    async def update_profile(self, user_id: int, payload: UserUpdatePayload) -> UserProfilePayload:
        user = await self.repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.status != "active":
            raise BizError("账号已禁用，无法修改资料")
        if payload.email is not None and payload.email != user.email:
            occupied = await self.repository.find_by_email(payload.email, user.id)
            if occupied is not None:
                raise BizError("该邮箱已被其他账号使用")
        changed = False
        if payload.display_name is not None:
            user.display_name = payload.display_name
            changed = True
        if payload.email is not None:
            user.email = payload.email
            changed = True
        if payload.phone is not None:
            user.phone = payload.phone
            changed = True
        if not changed:
            raise BizError("请至少提供一个要修改的字段")
        user = await self.repository.save(user)
        return UserProfilePayload.model_validate(user)
