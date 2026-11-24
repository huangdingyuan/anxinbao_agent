"""方案相关 payload，字段与前端 PlanInterruptCard / PlanSummary 的读取约定对齐"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class PlanItemPayload(BaseModel):
    """方案产品项"""

    id: UUID
    plan_id: UUID
    product_id: int | None = None
    name: str
    category: str
    annual_premium_budget: Decimal | None = None
    recommendation_reason: str | None = None
    status: str


class PlanPayload(BaseModel):
    """保障方案"""

    id: UUID
    name: str
    summary: str | None = None
    annual_premium_budget: Decimal | None = None
    status: str
    items: list[PlanItemPayload]


class PlanInterruptPayload(BaseModel):
    """方案确认中断事件"""

    plan: PlanPayload
    confirm_info: str
    action: list[str] = ["approve", "reject"]
