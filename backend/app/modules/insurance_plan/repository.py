from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import InsurancePlan, InsurancePlanItem


class InsurancePlanRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, plan: InsurancePlan, items: list[InsurancePlanItem]):
        # 通过 relationship 挂载，flush 时自动回填 plan_id 并按依赖顺序插入
        plan.items.extend(items)
        self.session.add(plan)
        await self.session.flush()

    async def get_with_items(self, plan_id: UUID) -> InsurancePlan | None:
        """按 id 查询方案并预加载产品项"""
        result = await self.session.execute(
            select(InsurancePlan)
            .where(InsurancePlan.id == plan_id)
            .options(selectinload(InsurancePlan.items))
        )
        return result.scalar_one_or_none()

    async def find_pending_by_thread(self, thread_id: UUID) -> InsurancePlan | None:
        """查询会话中最近一个待确认的方案（含产品项）"""
        result = await self.session.execute(
            select(InsurancePlan)
            .where(
                InsurancePlan.thread_id == thread_id,
                InsurancePlan.decision_status == "pending",
            )
            .order_by(InsurancePlan.created_at.desc())
            .limit(1)
            .options(selectinload(InsurancePlan.items))
        )
        return result.scalar_one_or_none()

    async def find_items(self, plan_id: UUID) -> Sequence[InsurancePlanItem]:
        result = await self.session.execute(
            select(InsurancePlanItem).where(InsurancePlanItem.plan_id == plan_id)
        )
        return result.scalars().all()
