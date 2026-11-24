"""本地知识库模块

保险条款与费率表经 MinerU 解析清洗后切块入库，供问答模块做条款参考检索。
"""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class KbDocument(Base, CreateAtMixin, UpdateAtMixin):
    """知识库文档，对应一份条款/费率表 PDF"""

    __tablename__ = "kb_documents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # 原始文件名（去扩展名），入库去重的依据
    source_name: Mapped[str] = mapped_column(String(200), unique=True)
    # kb 保险条款 / rate_table 费率表
    category: Mapped[str] = mapped_column(String(20))
    file_path: Mapped[str] = mapped_column(String(500))
    # 从文件名推导的产品名（去掉「条款」「费率表」等后缀）
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # pending 待解析 / parsed 已解析入库 / failed 解析失败
    parse_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class KbChunk(Base, CreateAtMixin):
    """文档切块，条款按章节切分，费率表按表格切分"""

    __tablename__ = "kb_chunks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
    )
    # 文档内块序号，保证展示顺序稳定
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 内容所在页码（MinerU content_list 的 page_idx，0 起）
    page_no: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 所属条款标题（如「第五条 保险责任」）
    heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    # 归一化 float32 向量（numpy tobytes），未计算为 NULL
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
