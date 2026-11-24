"""用户模块 payload"""

from datetime import datetime, timezone, timedelta

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

CN_TZ = timezone(timedelta(hours=8))


class UserProfilePayload(BaseModel):
    """用户个人资料"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    phone: str | None = None
    display_name: str | None = None
    status: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(CN_TZ).isoformat()


class UserUpdatePayload(BaseModel):
    """个人资料编辑（至少提供一个字段）"""

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)


class LoginPayload(BaseModel):
    """登录请求"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=120)


class LoginResult(BaseModel):
    """登录成功响应：JWT 访问令牌 + 用户资料"""

    access_token: str
    token_type: str = "bearer"
    user: UserProfilePayload
