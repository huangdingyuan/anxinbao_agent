"""保单服务

保障权益解析：按产品名匹配条款知识库文档，提取保险责任、责任免除等关键章节。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.knowledge.repository import KnowledgeRepository
from .models import Policy
from .repository import PolicyRepository
from .schemas import CN_TZ, PolicyBenefitItem, PolicyBenefitsPayload, PolicyPayload

# 到期提醒阈值（天）
EXPIRE_SOON_DAYS = 30
# 保障权益提取的关键章节关键词（按展示顺序）
BENEFIT_SECTIONS = ("保险责任", "责任免除", "等待期", "犹豫期", "宽限期", "续保", "免赔额")


class PolicyService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = PolicyRepository(session)
        self.knowledge_repository = KnowledgeRepository(session)

    async def list_policies(self, user_id: int) -> list[Policy]:
        return list(await self.repository.find_by_user(user_id))

    async def get_policy(self, user_id: int, policy_id: UUID) -> Policy:
        policy = await self.repository.get_owned(policy_id, user_id)
        if policy is None:
            raise NotFoundError("保单不存在")
        return policy

    async def get_policy_benefits(self, user_id: int, policy_id: UUID) -> PolicyBenefitsPayload:
        """解析保单对应产品的条款权益章节（知识库无匹配时返回空列表）"""
        policy = await self.get_policy(user_id, policy_id)
        product_name = policy.product.name if policy.product else None
        payload = PolicyBenefitsPayload(policy_id=policy.id, product_name=product_name)
        document = await self.knowledge_repository.find_kb_document_by_product_name(product_name)
        if document is None:
            return payload
        payload.document_name = document.product_name or document.source_name
        chunks = await self.knowledge_repository.find_chunks_by_document(document.id)
        for section in BENEFIT_SECTIONS:
            chunk = next(
                (
                    c
                    for c in chunks
                    if (c.heading and section in c.heading)
                    or (not c.heading and section in c.content[:60])
                ),
                None,
            )
            if chunk is None:
                continue
            payload.benefits.append(
                PolicyBenefitItem(
                    section=section,
                    heading=chunk.heading,
                    page_no=chunk.page_no,
                    content=chunk.content,
                )
            )
        return payload


def build_policy_payload(policy: Policy) -> PolicyPayload:
    payload = PolicyPayload.model_validate(policy)
    if policy.expires_at is not None:
        today = datetime.now(CN_TZ).date()
        payload.days_to_expire = (policy.expires_at.astimezone(CN_TZ).date() - today).days
        payload.expire_soon = (
            policy.status == "active" and 0 <= payload.days_to_expire <= EXPIRE_SOON_DAYS
        )
    return payload
