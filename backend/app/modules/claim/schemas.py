"""理赔 payload 与请求体，字段与前端展示约定对齐"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

CN_TZ = timezone(timedelta(hours=8))


class ClaimPolicySummary(BaseModel):
    """理赔关联的保单摘要"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_number: str
    product_name: str | None = None


class ClaimPayload(BaseModel):
    """理赔详情"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_number: str | None = None
    status: str
    claim_type: str
    amount: Decimal | None = None
    description: str | None = None
    policy: ClaimPolicySummary
    submitted_at: datetime
    updated_at: datetime

    @field_serializer("submitted_at", "updated_at")
    def serialize_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(CN_TZ).isoformat()


class ClaimCreateRequest(BaseModel):
    """提交理赔申请的请求体"""

    policy_id: UUID
    claim_type: Literal["medical", "accident", "critical_illness", "life"]
    amount: Decimal | None = None
    description: str | None = None


class ClaimStatusUpdateRequest(BaseModel):
    """推进理赔状态的请求体"""

    status: Literal["reviewing", "approved", "rejected", "paid"]
