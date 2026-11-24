from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator

# 北京时间（中国无夏令时，固定 +8）
CN_TZ = timezone(timedelta(hours=8))


class ChatThreadCreate(BaseModel):
    """创建会话请求"""

    title: str = Field(default="新会话", min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class ChatThreadUpdate(BaseModel):
    """重命名会话请求"""

    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return value.strip()


class ChatThreadResponse(BaseModel):
    """会话响应"""

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> datetime:
        # 数据库驱动固定返回 UTC，统一转成北京时间输出
        return value.astimezone(CN_TZ)