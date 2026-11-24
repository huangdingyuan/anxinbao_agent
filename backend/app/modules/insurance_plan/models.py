from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class InsurancePlan(Base, CreateAtMixin, UpdateAtMixin):
    """AI 推荐的保障方案

    status 为投保生命周期（uninsured/applying/insured），
    decision_status 为本次问答的确认状态（pending/approved/rejected）。
    """

    __tablename__ = "insurance_plans"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    thread_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    plan_name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text)
    # 投保人画像快照（年龄、预算等），由问答上下文填充
    insured_profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    annual_premium_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(
        String(30),
        default="uninsured",
        server_default="uninsured",
    )
    decision_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
    )

    items: Mapped[list["InsurancePlanItem"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="InsurancePlanItem.created_at",
    )


class InsurancePlanItem(Base, CreateAtMixin, UpdateAtMixin):
    """方案中的产品项"""

    __tablename__ = "insurance_plan_items"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("insurance_plans.id", ondelete="CASCADE"),
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
    )
    name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))
    recommendation_reason: Mapped[str | None] = mapped_column(Text)
    annual_premium_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # uninsured 未投保 / insured 已投保
    status: Mapped[str] = mapped_column(
        String(30),
        default="uninsured",
        server_default="uninsured",
    )

    plan: Mapped["InsurancePlan"] = relationship(back_populates="items")
