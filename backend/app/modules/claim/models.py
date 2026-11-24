"""理赔模块

复用数据库已有 claims 表，针对用户名下保单提交理赔申请并跟踪进度。
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.models import Base, UpdateAtMixin

# 显式导入外键目标表模型，确保同一 Base.metadata 完整注册
import app.modules.products.models  # noqa: F401,E402
import app.modules.policy.models  # noqa: F401,E402


class Claim(Base, UpdateAtMixin):
    """理赔申请，挂在用户名下保单上"""

    __tablename__ = "claims"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[int] = mapped_column(BigInteger)
    product_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
        nullable=True,
    )
    # 与保单的关联，理赔必须针对具体保单
    policy_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("policies.id"),
        nullable=True,
    )
    # medical 医疗 / accident 意外 / critical_illness 重疾 / life 寿险
    claim_type: Mapped[str] = mapped_column(String(50))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # submitted 已提交 / reviewing 审核中 / approved 已通过 / rejected 已拒绝 / paid 已赔付
    status: Mapped[str] = mapped_column(String(30), default="submitted", server_default="submitted")
    claim_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    policy = relationship("Policy", lazy="joined")
