"""知识库数据访问"""

from uuid import UUID

from sqlalchemy import String, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import KbChunk, KbDocument


class KnowledgeRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_documents(self, category: str | None = None) -> list[KbDocument]:
        stmt = select(KbDocument).order_by(KbDocument.category, KbDocument.source_name)
        if category:
            stmt = stmt.where(KbDocument.category == category)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_document(self, document_id: UUID) -> KbDocument | None:
        return await self.session.get(KbDocument, document_id)

    async def get_by_source_name(self, source_name: str) -> KbDocument | None:
        result = await self.session.execute(
            select(KbDocument).where(KbDocument.source_name == source_name)
        )
        return result.scalar_one_or_none()

    async def find_kb_document_by_product_name(self, product_name: str | None) -> KbDocument | None:
        """按产品名匹配条款文档（product_name 与产品名互相包含即视为匹配），取重叠最长者"""
        cleaned = (product_name or "").strip()
        if not cleaned:
            return None
        docs = [
            doc
            for doc in await self.find_documents("kb")
            if doc.parse_status == "parsed" and doc.product_name
        ]
        matched = [
            doc
            for doc in docs
            if doc.product_name in cleaned or cleaned in doc.product_name
        ]
        if not matched:
            return None
        return max(matched, key=lambda doc: len(doc.product_name or ""))

    async def find_chunks_by_document(self, document_id: UUID) -> list[KbChunk]:
        result = await self.session.execute(
            select(KbChunk)
            .where(KbChunk.document_id == document_id)
            .order_by(KbChunk.seq)
        )
        return list(result.scalars().all())

    async def delete_chunks_by_document(self, document_id: UUID) -> None:
        await self.session.execute(delete(KbChunk).where(KbChunk.document_id == document_id))

    async def find_candidates_by_keywords(
        self, keywords: list[str], limit: int = 200
    ) -> list[tuple[KbChunk, KbDocument]]:
        """按关键词 ILIKE 粗筛候选块（任一关键词命中即入选），连同文档信息返回"""
        conditions = [KbChunk.content.ilike(f"%{kw}%") for kw in keywords]
        result = await self.session.execute(
            select(KbChunk, KbDocument)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
            .where(KbDocument.parse_status == "parsed")
            .where(or_(*conditions))
            .limit(limit)
        )
        return list(result.all())

    async def count_chunks(self, document_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(KbChunk).where(KbChunk.document_id == document_id)
        )
        return int(result.scalar_one() or 0)

    async def count_chunks_with_embedding(self) -> int:
        """已计算向量的块数（用于内存缓存失效判断）"""
        result = await self.session.execute(
            select(func.count())
            .select_from(KbChunk)
            .where(KbChunk.embedding.is_not(None))
        )
        return int(result.scalar_one() or 0)

    async def find_chunks_with_embedding(self) -> list[KbChunk]:
        """全部已计算向量的块（小规模知识库，内存余弦检索）"""
        result = await self.session.execute(
            select(KbChunk).where(KbChunk.embedding.is_not(None))
        )
        return list(result.scalars().all())

    async def save_embeddings(self, pairs: list[tuple[UUID, bytes]]) -> None:
        """按块 id 批量回写向量"""
        for chunk_id, vector in pairs:
            await self.session.execute(
                update(KbChunk).where(KbChunk.id == chunk_id).values(embedding=vector)
            )
        await self.session.commit()
