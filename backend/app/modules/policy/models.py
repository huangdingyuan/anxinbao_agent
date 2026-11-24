"""保单模块

复用数据库已有 policies 表，投保成功后由方案产品项自动生成保单。
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base, CreateAtMixin, UpdateAtMixin

# 显式导入外键目标表模型，确保同一 Base.metadata 完整注册
import app.modules.products.models  # noqa: F401,E402
import app.modules.insurance_plan.models  # noqa: F401,E402


class Policy(Base, CreateAtMixin, UpdateAtMixin):
    """保单，投保成功后生成"""

    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
    )
    # 与保障方案的关联：由方案产品项投保生成
    plan_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("insurance_plans.id", ondelete="SET NULL"),
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("insurance_plan_items.id", ondelete="SET NULL"),
    )
    policy_number: Mapped[str] = mapped_column(String(60), unique=True)
    # pending 待生效 / active 生效中 / expired 已到期 / terminated 已终止
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    application_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    insured_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    insured_id_no_masked: Mapped[str | None] = mapped_column(String(40), nullable=True)
    insured_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    beneficiary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 投保时的方案/产品项快照
    policy_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    coverage_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product = relationship("Product", lazy="joined")
