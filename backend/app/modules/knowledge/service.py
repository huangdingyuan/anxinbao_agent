"""知识库服务：切块入库、文档/切块查询、混合检索（关键词 + 向量语义）

切块策略：
- 保险条款（kb）：按「第X章/第X条」标题锚点切分，超长块再按长度二次切分
- 费率表（rate_table）：每个表格独立成块（HTML 表格转管道分隔文本），零散文字按页合并
检索策略：混合检索——
- 关键词路：pg_trgm 索引 ILIKE 粗筛 + Python bigram 精排
- 向量路：本地 bge 模型语义向量，内存余弦 top-k（小规模数据不依赖 pgvector）
- 两路排序用 RRF（Reciprocal Rank Fusion）融合
"""

import html as html_mod
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.common import milvus
from . import embedder
from .models import KbChunk, KbDocument
from .repository import KnowledgeRepository
from .schemas import KbSearchItem

logger = get_logger(__name__)

# 章节标题锚点：第X章 / 第X条（支持中文数字与阿拉伯数字），仅识别短行
HEADING_PATTERN = re.compile(r"^第[一二三四五六七八九十百零\d]+[章条]")
HEADING_MAX_LEN = 60

# 单块内容长度上限，超过则二次切分
MAX_CHUNK_LEN = 800
# 检索命中阈值：至少命中 2 个问题关键词
MIN_SEARCH_SCORE = 2
# 参与粗筛/精排的问题关键词数上限
MAX_KEYWORDS = 10


@dataclass
class ParsedBlock:
    """MinerU content_list 中一个块的最小化表示"""

    type: str = "text"
    text: str = ""
    text_level: int | None = None
    page_idx: int = 0
    table_body: str = ""
    table_footnote: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """一份解析完成的文档"""

    source_name: str
    category: str  # kb / rate_table
    file_path: str
    content_list: list[ParsedBlock]


@dataclass
class BuiltChunk:
    """切块结果"""

    seq: int
    page_no: int
    heading: str | None
    content: str


def parse_content_list(raw_items: Iterable[dict]) -> list[ParsedBlock]:
    """把 MinerU content_list 原始字典转成 ParsedBlock"""
    blocks: list[ParsedBlock] = []
    for item in raw_items:
        blocks.append(
            ParsedBlock(
                type=item.get("type", "text"),
                text=(item.get("text") or "").strip(),
                text_level=int(item["text_level"]) if item.get("text_level") is not None else None,
                page_idx=int(item.get("page_idx") or 0),
                table_body=item.get("table_body") or "",
                table_footnote=item.get("table_footnote") or [],
            )
        )
    return blocks


def table_html_to_text(table_body: str) -> str:
    """把 MinerU 输出的 HTML 表格转成行「a | b | c」形式，便于模型阅读"""
    text = html_mod.unescape(table_body)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S)
    lines = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _is_heading(block: ParsedBlock) -> bool:
    """标题块判定：MinerU 标记的层级标题，或形如「第X章/第X条」的短行"""
    if block.type != "text" or not block.text:
        return False
    if block.text_level is not None and block.text_level <= 2 and len(block.text) <= HEADING_MAX_LEN:
        return True
    return bool(HEADING_PATTERN.match(block.text)) and len(block.text) <= HEADING_MAX_LEN


def _flush(chunks: list[BuiltChunk], state: dict) -> None:
    """把当前累积内容落成一块（空内容跳过）"""
    content = "\n".join(line for line in state["lines"] if line.strip())
    if content:
        chunks.append(
            BuiltChunk(
                seq=len(chunks),
                page_no=state["page_no"],
                heading=state["heading"],
                content=content[:MAX_CHUNK_LEN * 2],  # 兜底，正常不会触达
            )
        )
    state["lines"] = []


def _split_overlong(chunks: list[BuiltChunk]) -> None:
    """对超过 MAX_CHUNK_LEN 的块按段落二次切分，保持标题不变"""
    result: list[BuiltChunk] = []
    for chunk in chunks:
        if len(chunk.content) <= MAX_CHUNK_LEN:
            result.append(chunk)
            continue
        parts = chunk.content.split("\n")
        buffer: list[str] = []
        for part in parts:
            if buffer and sum(len(x) for x in buffer) + len(part) > MAX_CHUNK_LEN:
                result.append(
                    BuiltChunk(seq=0, page_no=chunk.page_no, heading=chunk.heading, content="\n".join(buffer))
                )
                buffer = []
            buffer.append(part)
        if buffer:
            result.append(
                BuiltChunk(seq=0, page_no=chunk.page_no, heading=chunk.heading, content="\n".join(buffer))
            )
    for i, chunk in enumerate(result):
        chunk.seq = i
    chunks[:] = result


def build_chunks_kb(blocks: list[ParsedBlock]) -> list[BuiltChunk]:
    """保险条款：按章节标题锚点切分"""
    chunks: list[BuiltChunk] = []
    state: dict = {"heading": None, "lines": [], "page_no": 0, "size": 0}
    for block in blocks:
        if _is_heading(block):
            _flush(chunks, state)
            state["heading"] = block.text[:200]
            state["page_no"] = block.page_idx
            state["size"] = 0
            # 标题本身保留为块内第一行
            state["lines"].append(block.text)
            state["size"] += len(block.text)
            continue
        if block.type == "table":
            table_text = table_html_to_text(block.table_body)
            footnote = "\n".join(block.table_footnote)
            state["lines"].append("\n".join(x for x in (table_text, footnote) if x.strip()))
            state["size"] += len(table_text)
        elif block.text:
            state["lines"].append(block.text)
            state["size"] += len(block.text)
        # 单块超限即落盘，标题延续
        if state["size"] >= MAX_CHUNK_LEN:
            _flush(chunks, state)
    _flush(chunks, state)
    _split_overlong(chunks)
    return chunks


def build_chunks_rate_table(blocks: list[ParsedBlock]) -> list[BuiltChunk]:
    """费率表：每个表格独立成块，零散文字按页合并"""
    chunks: list[BuiltChunk] = []
    state: dict = {"heading": None, "lines": [], "page_no": 0}
    for block in blocks:
        if block.type == "table":
            # 落盘表格前的文字
            _flush(chunks, state)
            parts = [table_html_to_text(block.table_body)]
            if block.table_footnote:
                parts.append("\n".join(block.table_footnote))
            content = "\n".join(p for p in parts if p.strip())
            if content:
                chunks.append(
                    BuiltChunk(
                        seq=len(chunks),
                        page_no=block.page_idx,
                        heading=block.text or "费率表",
                        content=content,
                    )
                )
            state["page_no"] = block.page_idx
            continue
        if block.text:
            if _is_heading(block):
                state["heading"] = block.text[:200]
            state["lines"].append(block.text)
            if block.page_idx != state["page_no"]:
                _flush(chunks, state)
                state["page_no"] = block.page_idx
    _flush(chunks, state)
    _split_overlong(chunks)
    return chunks


def build_chunks(category: str, blocks: list[ParsedBlock]) -> list[BuiltChunk]:
    if category == "rate_table":
        return build_chunks_rate_table(blocks)
    return build_chunks_kb(blocks)


def extract_bigrams(text: str) -> list[str]:
    """提取相邻二字片段并去重保序，用于关键词匹配"""
    cleaned = "".join(ch for ch in text if ch.isalnum())
    seen: set[str] = set()
    ordered: list[str] = []
    for i in range(len(cleaned) - 1):
        bg = cleaned[i:i + 2]
        if bg not in seen:
            seen.add(bg)
            ordered.append(bg)
    return ordered[:MAX_KEYWORDS]


# ---------- 向量内存缓存 ----------
# 小规模知识库（数千块）全量加载向量矩阵，余弦检索毫秒级；块数变化自动失效
_vector_cache_lock = threading.Lock()
_vector_cache: dict | None = None  # {"count": int, "ids": list[UUID], "docs": list[KbDocument], "chunks": list[KbChunk], "matrix": np.ndarray}


def _invalidate_vector_cache() -> None:
    """入库/回写向量后调用，强制下次检索重新加载"""
    global _vector_cache
    _vector_cache = None


class KnowledgeService:

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = KnowledgeRepository(session)

    # ---------- 入库 ----------
    async def ingest_document(
        self,
        source_name: str,
        category: str,
        file_path: str,
        blocks: list[ParsedBlock] | None,
        error: str | None = None,
    ) -> KbDocument:
        """按 source_name upsert 文档并重建切块；blocks 为空记为解析失败"""
        chunks = build_chunks(category, blocks or [])
        doc = await self.repository.get_by_source_name(source_name)
        if doc is None:
            doc = KbDocument(source_name=source_name, category=category, file_path=file_path)
            self.session.add(doc)
            await self.session.flush()
        doc.category = category
        doc.file_path = file_path
        if blocks:
            doc.parse_status = "parsed"
            doc.error = None
        else:
            doc.parse_status = "failed"
            doc.error = error
        if blocks:
            await self.repository.delete_chunks_by_document(doc.id)
            await self.session.flush()  # 先清空旧块
            new_chunks = [
                KbChunk(
                    document_id=doc.id,
                    seq=chunk.seq,
                    page_no=chunk.page_no,
                    heading=chunk.heading,
                    content=chunk.content,
                )
                for chunk in chunks
            ]
            self.session.add_all(new_chunks)
            await self.session.flush()  # 拿到块 id
            await self._fill_embeddings(new_chunks)
            doc.chunk_count = len(new_chunks)
            await self._sync_document_to_milvus(doc, new_chunks)
        else:
            doc.chunk_count = 0
        _invalidate_vector_cache()
        return doc

    async def _fill_embeddings(self, chunks: list[KbChunk]) -> None:
        """入库时批量计算块向量；模型不可用则跳过（检索自动降级关键词）"""
        started = time.perf_counter()
        vectors = embedder.encode_texts([c.content for c in chunks])
        if vectors is None:
            return
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector.tobytes()
        logger.info(
            f"向量编码 {len(chunks)} 块完成，耗时 {time.perf_counter() - started:.1f}s"
        )

    async def _sync_document_to_milvus(self, doc: KbDocument, chunks: list[KbChunk]) -> None:
        """把带向量的块同步到 Milvus（先删旧再插新）；失败不影响入库"""
        vectorized = [c for c in chunks if c.embedding is not None]
        if not vectorized:
            return
        try:
            milvus.delete_by_document(str(doc.id))
            rows = []
            for chunk in vectorized:
                vec = np.frombuffer(chunk.embedding, dtype=np.float32)
                rows.append({
                    "chunk_id": str(chunk.id),
                    "document_id": str(doc.id),
                    "category": doc.category,
                    "source_name": doc.source_name,
                    "product_name": doc.product_name or "",
                    "page_no": chunk.page_no,
                    "heading": chunk.heading or "",
                    "content": chunk.content[:60000],
                    "embedding": vec.tolist(),
                })
            milvus.upsert_chunks(rows)
            logger.info(f"Milvus 同步完成：文档 {doc.source_name} 共 {len(rows)} 块")
        except Exception as exc:
            logger.warning(f"Milvus 同步失败（检索降级内存余弦）: {exc!r}")

    async def backfill_embeddings(self, batch_size: int = 64) -> int:
        """为存量无向量块补算向量，返回本次补算数量"""
        total = 0
        while True:
            result = await self.session.execute(
                select(KbChunk)
                .where(KbChunk.embedding.is_(None))
                .limit(batch_size)
            )
            pending = list(result.scalars().all())
            if not pending:
                break
            await self._fill_embeddings(pending)
            await self.session.commit()
            total += len(pending)
        if total:
            _invalidate_vector_cache()
        return total

    # ---------- 查询 ----------
    async def list_documents(self, category: str | None = None) -> list[KbDocument]:
        return await self.repository.find_documents(category)

    async def list_chunks(self, document_id: UUID) -> list[KbChunk]:
        doc = await self.repository.get_document(document_id)
        if doc is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError("知识库文档不存在")
        return await self.repository.find_chunks_by_document(document_id)

    # ---------- 检索 ----------
    async def _get_vector_index(self) -> dict | None:
        """加载（并缓存）全部块向量矩阵；无向量或模型不可用返回 None"""
        global _vector_cache
        with _vector_cache_lock:
            if _vector_cache is not None:
                return _vector_cache
        chunks = await self.repository.find_chunks_with_embedding()
        if not chunks:
            return None
        vectors = [np.frombuffer(chunk.embedding, dtype=np.float32) for chunk in chunks]
        dim = vectors[0].shape[0]
        if any(v.shape[0] != dim for v in vectors):
            logger.warning("存在维度不一致的向量，跳过本轮向量检索")
            return None
        cache = {
            "count": len(chunks),
            "chunks": chunks,
            "matrix": np.vstack(vectors),
        }
        with _vector_cache_lock:
            if _vector_cache is None:
                _vector_cache = cache
        return _vector_cache or cache

    async def _vector_search(
        self, query_vec: np.ndarray, top_n: int
    ) -> list[tuple[UUID, float]]:
        """语义向量检索：优先 Milvus，不可用降级内存余弦

        返回 [(chunk_id, similarity)] 按相似度降序
        """
        # 路 A：Milvus HNSW 检索
        try:
            hits = milvus.search_similar(query_vec, top_n)
            if hits:
                return [
                    (UUID(item["chunk_id"]), item["similarity"])
                    for item in hits
                    if item["similarity"] > 0.55  # 低于阈值视为无关（闲聊/错误领域查询）
                ]
        except Exception as exc:
            logger.warning(f"Milvus 检索失败，降级内存余弦: {exc!r}")

        # 路 B（降级）：内存矩阵余弦
        index = await self._get_vector_index()
        if index is None:
            return []
        sims = index["matrix"] @ query_vec  # 向量已归一化，点积即余弦相似度
        order = np.argsort(-sims)[:top_n]
        return [
            (index["chunks"][int(i)].id, float(sims[int(i)]))
            for i in order
            if sims[int(i)] > 0.55  # 相似度过低的直接丢弃
        ]

    async def search(self, query: str, top_k: int = 5) -> list[KbSearchItem]:
        """混合检索：关键词路 + 向量语义路，RRF 融合排序"""
        # 路一：关键词 ILIKE 粗筛 + bigram 精排
        keywords = extract_bigrams(query)
        keyword_ranked: list[KbChunk] = []
        if keywords:
            candidates = await self.repository.find_candidates_by_keywords(keywords)
            scored: list[tuple[int, KbChunk]] = []
            for chunk, _doc in candidates:
                hits = sum(1 for kw in keywords if kw in chunk.content)
                if hits < MIN_SEARCH_SCORE:
                    continue
                occurrences = sum(chunk.content.count(kw) for kw in keywords)
                scored.append((hits * 10 + min(occurrences, 20), chunk))
            scored.sort(key=lambda item: item[0], reverse=True)
            keyword_ranked = [chunk for _, chunk in scored]

        # 路二：向量语义余弦 top-N
        vector_ranked: list[tuple[UUID, float]] = []
        query_vec = embedder.encode_query(query)
        if query_vec is not None:
            try:
                vector_ranked = await self._vector_search(query_vec, top_n=20)
            except Exception as exc:
                logger.warning(f"向量检索失败，降级纯关键词: {exc!r}")

        if not keyword_ranked and not vector_ranked:
            return []

        # RRF 融合：score = Σ 1/(k + rank)，k=60
        RRF_K = 60
        chunk_map: dict[UUID, KbChunk] = {}
        rrf_scores: dict[UUID, float] = {}
        for rank, chunk in enumerate(keyword_ranked, start=1):
            chunk_map.setdefault(chunk.id, chunk)
            rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
        for rank, (chunk_id, _sim) in enumerate(vector_ranked, start=1):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        # 向量路命中的块可能未进 chunk_map，需补齐实体
        missing_ids = [cid for cid in rrf_scores if cid not in chunk_map]
        if missing_ids:
            result = await self.session.execute(
                select(KbChunk).where(KbChunk.id.in_(missing_ids))
            )
            for chunk in result.scalars().all():
                chunk_map[chunk.id] = chunk

        fused = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)

        # 同一文档最多贡献一半的块，避免结果被单一条款刷屏
        per_doc_limit = max(1, top_k // 2 + 1)
        doc_counter: dict[UUID, int] = {}
        items: list[KbSearchItem] = []
        for chunk_id, score in fused:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            doc = await self.session.get(KbDocument, chunk.document_id)
            if doc is None or doc.parse_status != "parsed":
                continue
            if doc_counter.get(doc.id, 0) >= per_doc_limit:
                continue
            doc_counter[doc.id] = doc_counter.get(doc.id, 0) + 1
            items.append(
                KbSearchItem(
                    document_id=doc.id,
                    source_name=doc.source_name,
                    product_name=doc.product_name,
                    category=doc.category,
                    page_no=chunk.page_no + 1,  # 对外按 1 起算的页码
                    heading=chunk.heading,
                    content=chunk.content,
                    score=round(score, 4),
                )
            )
            if len(items) >= top_k:
                break
        return items
