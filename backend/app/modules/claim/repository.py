from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.policy.models import Policy
from .models import Claim


class ClaimRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _eager_options():
        # selectinload 加载理赔关联的保单，再 joinedload 保单的产品，
        # 避免 async 场景下访问 relationship 触发惰性加载抛 MissingGreenlet
        return (
            selectinload(Claim.policy).joinedload(Policy.product),
        )

    async def find_by_user(self, user_id: int, policy_id: UUID | None = None) -> Sequence[Claim]:
        """查询用户名下理赔申请，按提交时间倒序，可按保单过滤"""
        stmt = (
            select(Claim)
            .where(Claim.user_id == user_id)
            .options(*self._eager_options())
            .order_by(Claim.submitted_at.desc())
        )
        if policy_id is not None:
            stmt = stmt.where(Claim.policy_id == policy_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_owned(self, claim_id: UUID, user_id: int) -> Claim | None:
        """按 id 查询理赔申请，校验归属"""
        result = await self.session.execute(
            select(Claim)
            .where(Claim.id == claim_id, Claim.user_id == user_id)
            .options(*self._eager_options())
        )
        return result.scalar_one_or_none()
