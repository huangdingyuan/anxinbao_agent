"""理赔服务：提交申请、查询、状态流转"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError, NotFoundError
from app.modules.policy.repository import PolicyRepository
from .models import Claim
from .repository import ClaimRepository
from .schemas import ClaimPayload

# 理赔状态流转图：submitted -> reviewing -> approved/rejected，approved -> paid
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"reviewing"},
    "reviewing": {"approved", "rejected"},
    "approved": {"paid"},
    "rejected": set(),
    "paid": set(),
}

# 仅生效中的保单可发起理赔
CLAIMABLE_POLICY_STATUS = {"active"}


class ClaimService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = ClaimRepository(session)

    async def list_claims(self, user_id: int, policy_id: UUID | None = None) -> list[Claim]:
        return list(await self.repository.find_by_user(user_id, policy_id))

    async def get_claim(self, user_id: int, claim_id: UUID) -> Claim:
        claim = await self.repository.get_owned(claim_id, user_id)
        if claim is None:
            raise NotFoundError("理赔申请不存在")
        return claim

    async def create_claim(
        self,
        user_id: int,
        policy_id: UUID,
        claim_type: str,
        amount: Decimal | None,
        description: str | None,
    ) -> Claim:
        """针对用户名下生效中的保单提交理赔申请"""
        if amount is not None and amount <= 0:
            raise BizError("理赔金额必须大于 0")
        # 保单归属校验：不存在或非本人名下一律按不存在处理
        policy = await PolicyRepository(self.session).get_owned(policy_id, user_id)
        if policy is None:
            raise NotFoundError("保单不存在")
        if policy.status not in CLAIMABLE_POLICY_STATUS:
            raise BizError("仅生效中的保单可以发起理赔")
        now = datetime.now(UTC)
        claim = Claim(
            user_id=user_id,
            policy_id=policy.id,
            product_id=policy.product_id,
            claim_type=claim_type,
            amount=amount,
            description=description,
            status="submitted",
            claim_number=f"CLM-{now.strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}",
        )
        self.session.add(claim)
        await self.session.flush()
        # flush 后重新带预加载查询取回，避免访问 relationship 触发惰性加载
        return await self.repository.get_owned(claim.id, user_id)

    async def update_status(self, user_id: int, claim_id: UUID, next_status: str) -> Claim:
        """推进理赔状态，仅允许合法流转"""
        claim = await self.get_claim(user_id, claim_id)
        allowed = STATUS_TRANSITIONS.get(claim.status, set())
        if next_status not in allowed:
            raise BizError(f"理赔状态不允许从 {claim.status} 变更为 {next_status}")
        claim.status = next_status
        await self.session.flush()
        # 重新带预加载查询取回，确保 updated_at 与 relationship 均已加载
        return await self.repository.get_owned(claim.id, user_id)


def build_claim_payload(claim: Claim) -> ClaimPayload:
    payload = ClaimPayload.model_validate(claim)
    # 保单摘要补充产品名称（coverage_snapshot 由投保流程写入，缺省时回退产品表名称）
    product_name = (claim.policy.coverage_snapshot or {}).get("product_name")
    if not product_name and claim.policy.product is not None:
        product_name = claim.policy.product.name
    payload.policy.product_name = product_name
    return payload
