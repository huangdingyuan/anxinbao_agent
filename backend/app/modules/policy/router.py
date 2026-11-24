from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.deps import get_current_user_id, get_session
from .service import PolicyService, build_policy_payload
from .schemas import PolicyBenefitsPayload, PolicyPayload

router = APIRouter(prefix="/api/v1/policies", tags=["保单的接口"])


def get_service(session: AsyncSession = Depends(get_session)) -> PolicyService:
    return PolicyService(session)


@router.get("", response_model=list[PolicyPayload])
async def list_policies(
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: PolicyService = Depends(get_service),
):
    """查询当前用户的保单列表"""
    return [build_policy_payload(p) for p in await service.list_policies(user_id)]


@router.get("/{policy_id}", response_model=PolicyPayload)
async def get_policy(
        policy_id: UUID,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: PolicyService = Depends(get_service),
):
    """查询保单详情"""
    return build_policy_payload(await service.get_policy(user_id, policy_id))


@router.get("/{policy_id}/benefits", response_model=PolicyBenefitsPayload)
async def get_policy_benefits(
        policy_id: UUID,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: PolicyService = Depends(get_service),
):
    """解析保单对应产品的条款权益章节（联动条款知识库）"""
    return await service.get_policy_benefits(user_id, policy_id)
