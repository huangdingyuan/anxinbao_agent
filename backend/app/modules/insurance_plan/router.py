from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.common.deps import get_session
from app.modules.insurance_plan.schemas import PlanPayload
from app.modules.policy.repository import PolicyRepository
from app.modules.products.models import Product
from .repository import InsurancePlanRepository
from .service import build_plan_payload

router = APIRouter(prefix="/api/v1/insurance-plans", tags=["保障方案的接口"])


def get_repository(session: AsyncSession = Depends(get_session)):
    return InsurancePlanRepository(session)


async def _get_owned_plan(repository: InsurancePlanRepository, plan_id: UUID, user_id: int):
    plan = await repository.get_with_items(plan_id)
    if plan is None or plan.user_id != user_id:
        raise NotFoundError("保障方案不存在")
    return plan


@router.get("/{plan_id}", response_model=PlanPayload)
async def get_insurance_plan(
        plan_id: UUID,
        user_id: Annotated[int, Header(alias="x-user-id")],
        repository: InsurancePlanRepository = Depends(get_repository),
):
    """查询保障方案详情（含各产品项的投保状态）"""

    return build_plan_payload(await _get_owned_plan(repository, plan_id, user_id))


@router.patch("/{plan_id}/items/{item_id}/insured", response_model=PlanPayload)
async def mark_plan_item_insured(
        plan_id: UUID,
        item_id: UUID,
        user_id: Annotated[int, Header(alias="x-user-id")],
        repository: InsurancePlanRepository = Depends(get_repository),
        session: AsyncSession = Depends(get_session),
):
    """把方案中的产品项标记为已投保，并生成对应保单"""
    async with session.begin():
        await _get_owned_plan(repository, plan_id, user_id)
        items = await repository.find_items(plan_id)
        target = next((item for item in items if item.id == item_id), None)
        if target is None:
            raise NotFoundError("方案产品项不存在")
        target.status = "insured"
        await session.flush()
        # 投保成功自动生成保单（同一产品项不重复生成）
        policy_repository = PolicyRepository(session)
        if await policy_repository.find_by_item(item_id) is None:
            product = await session.get(Product, target.product_id)
            if product is None:
                raise NotFoundError("产品不存在")
            await policy_repository.create_from_item(user_id, target, product)
        # 同步方案投保生命周期：全部产品项投保完成则方案已投保
        plan = await repository.get_with_items(plan_id)
        if all(item.status == "insured" for item in plan.items):
            plan.status = "insured"
        elif plan.status == "uninsured":
            plan.status = "applying"
        await session.flush()
        plan = await repository.get_with_items(plan_id)
        return build_plan_payload(plan)
