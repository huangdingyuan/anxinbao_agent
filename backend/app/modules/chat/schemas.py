from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

# 北京时间（中国无夏令时，固定 +8）
CN_TZ = timezone(timedelta(hours=8))


class ChatAskRequest(BaseModel):
    """提问请求（内部 SSE 接口）"""

    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return value.strip()


class ChatFrontendAsk(BaseModel):
    """提问请求（前端契约）：POST /api/v1/chat"""

    thread_id: UUID | None = None
    message: str | None = Field(default=None, max_length=2000)
    decision: dict | None = None


class ChatMessageResponse(BaseModel):
    """消息响应"""

    model_config = ConfigDict(from_attributes=True)  # 支持从 ORM 对象直接转换

    id: UUID
    role: str
    content: str
    additional_info: list | dict | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> datetime:
        # 数据库驱动固定返回 UTC，统一转成北京时间输出
        return value.astimezone(CN_TZ)


class ChatHistoryResponse(BaseModel):
    """消息历史响应（前端契约）"""

    thread_id: UUID
    messages: list[ChatMessageResponse]
    interrupt: dict | None = None
