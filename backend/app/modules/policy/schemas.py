"""保单 payload，字段与前端展示约定对齐"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

CN_TZ = timezone(timedelta(hours=8))


class PolicyProductPayload(BaseModel):
    """保单对应的产品摘要"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    insurer: str | None = None
    category: str | None = None


class PolicyPayload(BaseModel):
    """保单详情"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_number: str
    status: str
    product: PolicyProductPayload
    plan_id: UUID | None = None
    item_id: UUID | None = None
    holder_name: str | None = None
    insured_name: str | None = None
    premium_amount: Decimal | None = None
    coverage_amount: Decimal | None = None
    payment_frequency: str | None = None
    effective_at: datetime
    expires_at: datetime | None = None
    # 距到期天数（按北京时间日期差），无到期日为 None；已到期为负数
    days_to_expire: int | None = None
    # 生效中且 30 天内到期，用于前端到期提醒
    expire_soon: bool = False
    paid_at: datetime | None = None
    issued_at: datetime | None = None
    created_at: datetime

    @field_serializer("effective_at", "expires_at", "paid_at", "issued_at", "created_at")
    def serialize_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(CN_TZ).isoformat()


class PolicyBenefitItem(BaseModel):
    """从条款知识库提取的保障权益章节"""

    section: str
    heading: str | None = None
    page_no: int = 0
    content: str


class PolicyBenefitsPayload(BaseModel):
    """保单保障权益解析结果（联动条款知识库）"""

    policy_id: UUID
    product_name: str | None = None
    document_name: str | None = None
    benefits: list[PolicyBenefitItem] = []
