from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.insurance_plan.models import InsurancePlanItem
from app.modules.products.models import Product
from .models import Policy


class PolicyRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_user(self, user_id: int) -> Sequence[Policy]:
        """查询用户名下全部保单，按投保时间倒序"""
        result = await self.session.execute(
            select(Policy)
            .where(Policy.user_id == user_id)
            .order_by(Policy.created_at.desc())
        )
        return result.scalars().all()

    async def get_owned(self, policy_id: UUID, user_id: int) -> Policy | None:
        """按 id 查询保单，校验归属"""
        policy = await self.session.get(Policy, policy_id)
        if policy is None or policy.user_id != user_id:
            return None
        return policy

    async def find_by_item(self, item_id: UUID) -> Policy | None:
        """按方案产品项查询已生成的保单（防止重复投保生成多张）"""
        result = await self.session.execute(
            select(Policy).where(Policy.item_id == item_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def create_from_item(
        self, user_id: int, item: InsurancePlanItem, product: Product
    ) -> Policy:
        """由方案产品项生成保单：次日零时生效，有效期 1 年"""
        now = datetime.now(UTC)
        effective_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        policy = Policy(
            user_id=user_id,
            product_id=product.id,
            plan_id=item.plan_id,
            item_id=item.id,
            policy_number=f"POL-{now.strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}",
            status="active",
            effective_at=effective_at,
            expires_at=effective_at + timedelta(days=365),
            premium_amount=item.annual_premium_budget,
            payment_frequency="annual",
            policy_snapshot={
                "plan_id": str(item.plan_id) if item.plan_id else None,
                "item_id": str(item.id),
                "item_name": item.name,
                "category": item.category,
            },
            coverage_snapshot={
                "product_name": product.name,
                "highlights": product.highlights or [],
            },
            paid_at=now,
            issued_at=now,
        )
        self.session.add(policy)
        await self.session.flush()
        return policy
