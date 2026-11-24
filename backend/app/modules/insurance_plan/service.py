from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.products.models import Product
from .models import InsurancePlan, InsurancePlanItem
from .repository import InsurancePlanRepository
from .schemas import PlanInterruptPayload, PlanItemPayload, PlanPayload

logger = get_logger(__name__)

CATEGORY_LABELS = {
    "medical": "医疗险",
    "critical_illness": "重疾险",
    "life": "寿险",
    "accident": "意外险",
}

CONFIRM_INFO = "是否保存这份保障方案？确认后可在产品卡片中发起投保，也可以继续调整。"


class InsurancePlanService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = InsurancePlanRepository(session)

    async def create_from_products(
        self, user_id: int, thread_id, products: list[Product]
    ) -> InsurancePlan:
        """根据回答中实际推荐的产品生成待确认方案"""
        items: list[InsurancePlanItem] = []
        total = Decimal("0")
        for product in products:
            premium = product.min_premium or Decimal("0")
            total += premium
            items.append(
                InsurancePlanItem(
                    product_id=product.id,
                    name=product.name,
                    category=product.category,
                    annual_premium_budget=premium or None,
                    recommendation_reason=product.target_group or product.description,
                )
            )
        plan = InsurancePlan(
            thread_id=thread_id,
            user_id=user_id,
            plan_name="智能保障方案",
            summary=f"根据你的需求从平台在售产品中挑选的 {len(items)} 款产品组合",
            insured_profile={},
            annual_premium_budget=total if total > 0 else None,
        )
        await self.repository.add(plan, items)
        # 不使用 session.refresh：异步会话中 refresh 会过期 items 关系，
        # 导致 build_interrupt 懒加载抛 MissingGreenlet；flush 后所需字段均已回填
        return plan

    async def decide_latest_pending(self, thread_id, decision_status: str) -> InsurancePlan | None:
        """把会话中最近一个待确认方案置为指定确认状态，没有则返回 None"""
        plan = await self.repository.find_pending_by_thread(thread_id)
        if plan is None:
            return None
        plan.decision_status = decision_status
        await self.session.flush()
        return plan


def build_plan_payload(plan: InsurancePlan) -> PlanPayload:
    return PlanPayload(
        id=plan.id,
        name=plan.plan_name,
        summary=plan.summary,
        annual_premium_budget=plan.annual_premium_budget,
        status=plan.status,
        items=[
            PlanItemPayload(
                id=item.id,
                plan_id=item.plan_id,
                product_id=item.product_id,
                name=item.name,
                category=item.category,
                annual_premium_budget=item.annual_premium_budget,
                recommendation_reason=item.recommendation_reason,
                status=item.status,
            )
            for item in plan.items
        ],
    )


def build_interrupt(plan: InsurancePlan) -> PlanInterruptPayload:
    return PlanInterruptPayload(plan=build_plan_payload(plan), confirm_info=CONFIRM_INFO)
