"""知识库接口：文档列表、切块浏览、关键词检索、触发入库"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.deps import get_session
from .ingest import ingest_from_parsed_dir
from .schemas import KbChunkPayload, KbDocumentPayload, KbIngestResult, KbSearchItem
from .service import KnowledgeService

router = APIRouter(prefix="/api/v1/knowledge", tags=["知识库的接口"])


def get_service(session: AsyncSession = Depends(get_session)) -> KnowledgeService:
    return KnowledgeService(session)


@router.get("/documents", response_model=list[KbDocumentPayload])
async def list_documents(
        category: Literal["kb", "rate_table"] | None = Query(default=None),
        service: KnowledgeService = Depends(get_service),
):
    """查询知识库文档列表，可按类型过滤（kb 条款 / rate_table 费率表）"""
    return await service.list_documents(category)


@router.get("/documents/{document_id}/chunks", response_model=list[KbChunkPayload])
async def list_chunks(
        document_id: UUID,
        service: KnowledgeService = Depends(get_service),
):
    """浏览文档的切块内容（按块序返回）"""
    return await service.list_chunks(document_id)


@router.get("/search", response_model=list[KbSearchItem])
async def search(
        q: Annotated[str, Query(min_length=2)],
        top_k: int = Query(default=5, ge=1, le=20),
        service: KnowledgeService = Depends(get_service),
):
    """按关键词检索条款切块，返回带来源信息的结果"""
    return await service.search(q, top_k)


@router.post("/ingest", response_model=KbIngestResult)
async def ingest(session: AsyncSession = Depends(get_session)):
    """把已解析好的知识库文件（scripts/parse_kb.py parse 产物）切块入库"""
    async with session.begin():
        return await ingest_from_parsed_dir(session)
