"""知识库 payload，字段与前端展示约定对齐"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

CN_TZ = timezone(timedelta(hours=8))


class KbDocumentPayload(BaseModel):
    """知识库文档摘要"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_name: str
    category: str
    product_name: str | None = None
    parse_status: str
    chunk_count: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(CN_TZ).isoformat()


class KbChunkPayload(BaseModel):
    """文档切块内容"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    seq: int
    page_no: int
    heading: str | None = None
    content: str


class KbSearchItem(BaseModel):
    """条款检索命中项，附来源信息便于引用"""

    document_id: UUID
    source_name: str
    product_name: str | None = None
    category: str
    page_no: int
    heading: str | None = None
    content: str
    # RRF 融合得分（多路命中叠加，仅用于排序展示）
    score: float


class KbIngestResult(BaseModel):
    """入库结果统计"""

    ingested: int
    total_chunks: int
    failed: list[str]
