from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.deps import get_current_user_id, get_session
from .schemas import ClaimCreateRequest, ClaimPayload, ClaimStatusUpdateRequest
from .service import ClaimService, build_claim_payload

router = APIRouter(prefix="/api/v1/claims", tags=["理赔的接口"])


def get_service(session: AsyncSession = Depends(get_session)) -> ClaimService:
    return ClaimService(session)


@router.get("", response_model=list[ClaimPayload])
async def list_claims(
        user_id: Annotated[int, Depends(get_current_user_id)],
        policy_id: UUID | None = Query(default=None),
        service: ClaimService = Depends(get_service),
):
    """查询当前用户的理赔申请列表，可按保单过滤"""
    return [build_claim_payload(c) for c in await service.list_claims(user_id, policy_id)]


@router.post("", response_model=ClaimPayload)
async def create_claim(
        user_id: Annotated[int, Depends(get_current_user_id)],
        request: ClaimCreateRequest,
        service: ClaimService = Depends(get_service),
        session: AsyncSession = Depends(get_session),
):
    """针对名下保单提交理赔申请"""
    async with session.begin():
        claim = await service.create_claim(
            user_id,
            request.policy_id,
            request.claim_type,
            request.amount,
            request.description,
        )
        return build_claim_payload(claim)


@router.get("/{claim_id}", response_model=ClaimPayload)
async def get_claim(
        claim_id: UUID,
        user_id: Annotated[int, Depends(get_current_user_id)],
        service: ClaimService = Depends(get_service),
):
    """查询理赔申请详情"""
    return build_claim_payload(await service.get_claim(user_id, claim_id))


@router.patch("/{claim_id}/status", response_model=ClaimPayload)
async def update_claim_status(
        claim_id: UUID,
        user_id: Annotated[int, Depends(get_current_user_id)],
        request: ClaimStatusUpdateRequest,
        service: ClaimService = Depends(get_service),
        session: AsyncSession = Depends(get_session),
):
    """推进理赔进度（演示用状态流转：提交 -> 审核 -> 通过/拒绝 -> 赔付）"""
    async with session.begin():
        claim = await service.update_status(user_id, claim_id, request.status)
        return build_claim_payload(claim)
