"""LangChain RAG 封装：把条款知识库、费率表、产品库三路检索包装为 BaseRetriever。

底层实现复用 retrieval.py / KnowledgeService（混合检索、RRF 融合、降级策略不变），
本模块只做 LangChain 接口适配，供 LangGraph Agent 图与 @tool 消费。

checkpoint 序列化约束：图状态里只允许 JSON-safe 数据，因此 ProductRetriever 的
metadata 存 _product_item 形状的 payload dict，而非 SQLAlchemy ORM 对象。
"""

import asyncio
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool

from app.core.logging import get_logger
from app.modules.products.models import Product

from .retrieval import (
    _longest_match_pos,
    retrieve_kb_chunks,
    retrieve_products_from_db,
    retrieve_rate_table_rows,
)

logger = get_logger(__name__)


def product_payload(p: Product) -> dict[str, Any]:
    """产品 ORM -> JSON-safe payload（与 service._product_item 形状一致）"""
    return {
        "id": p.id,
        "product_id": p.id,
        "name": p.name,
        "category": p.category,
        "insurer": p.insurer,
        "image_url": p.image_url,
        "description": p.description or "",
        "highlights": p.highlights or [],
    }


def _to_documents(items: list[dict]) -> list[Document]:
    """检索结果 dict（含 content）-> LangChain Document"""
    docs: list[Document] = []
    for item in items:
        metadata = {k: v for k, v in item.items() if k != "content"}
        docs.append(Document(page_content=item.get("content") or "", metadata=metadata))
    return docs


class ClauseRetriever(BaseRetriever):
    """条款知识库混合检索（关键词 + 向量语义 + RRF 融合），包 KnowledgeService.search"""

    top_k: int = 4

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        items = await retrieve_kb_chunks(query, top_k=self.top_k)
        return _to_documents(items)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        # 同步桥仅脚本/测试使用；服务内一律走异步路径
        return asyncio.run(self.ainvoke(query))


class RateTableRetriever(BaseRetriever):
    """费率表精确行检索：问题含「年龄+性别+交费期」维度时命中原表确切行"""

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        items = await retrieve_rate_table_rows(query)
        return _to_documents(items)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return asyncio.run(self.ainvoke(query))


class ProductRetriever(BaseRetriever):
    """产品库关键词匹配检索，metadata 存 payload dict 保证 checkpoint JSON-safe"""

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        products = await retrieve_products_from_db(query)
        return [
            Document(
                page_content=f"{p.name}（{p.insurer}）",
                metadata=product_payload(p),
            )
            for p in products
        ]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return asyncio.run(self.ainvoke(query))


clause_retriever = ClauseRetriever()
rate_table_retriever = RateTableRetriever()
product_retriever = ProductRetriever()


def _doc_to_ref(doc: Document) -> dict:
    """条款/费率 Document -> 与现 KbSearchItem dict 同形状的引用条目"""
    return {"content": doc.page_content, **doc.metadata}


async def gather_references(
    question: str, tasks: list[str]
) -> tuple[list[dict], list[dict]]:
    """按 tasks 并行检索，返回 (产品 payload 列表, 条款/费率引用列表)。

    费率表精确行优先（已裁剪到目标维度），与语义结果按 文档+页码 去重；
    任一路失败由 retriever 内部降级为空，不影响其他路。
    """
    jobs: dict[str, Any] = {}
    if "products" in tasks:
        jobs["products"] = product_retriever.ainvoke(question)
    if "clauses" in tasks:
        jobs["clauses"] = clause_retriever.ainvoke(question)
    if "rates" in tasks:
        jobs["rates"] = rate_table_retriever.ainvoke(question)
    if not jobs:
        return [], []

    results = await asyncio.gather(*jobs.values())
    named = dict(zip(jobs.keys(), results))

    products = [doc.metadata for doc in named.get("products", [])]
    rate_refs = [_doc_to_ref(d) for d in named.get("rates", [])]
    clause_refs = [_doc_to_ref(d) for d in named.get("clauses", [])]

    merged: list[dict] = list(rate_refs)
    seen: set[tuple] = {(r.get("source_name"), r.get("page_no")) for r in rate_refs}
    for ref in clause_refs:
        key = (ref.get("source_name"), ref.get("page_no"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(ref)
    return products, merged


def filter_mentioned_by_payload(products: list[dict], answer: str) -> list[dict]:
    """从候选产品 payload 中筛出回答里实际提及的，按首次提及位置排序"""
    matched: list[tuple[int, dict]] = []
    for p in products:
        pos = _longest_match_pos(p["name"], answer)
        if pos >= 0:
            matched.append((pos, p))
    matched.sort(key=lambda pair: pair[0])
    return [p for _, p in matched]


# ---------- @tool 包装（预留 ReAct 升级入口，当前图不消费） ----------

@tool
async def search_clauses(question: str) -> str:
    """检索保险条款知识库（保障责任、免责、犹豫期等条款原文摘录），输入用户问题"""
    docs = await clause_retriever.ainvoke(question)
    return "\n\n".join(
        f"来源：{d.metadata.get('product_name') or d.metadata.get('source_name')}"
        f"（{d.metadata.get('heading') or '未标注章节'}，第 {d.metadata.get('page_no', 1)} 页）\n{d.page_content}"
        for d in docs
    ) or "未检索到相关条款"


@tool
async def query_rate_table(question: str) -> str:
    """查询费率表精确行（需问题含年龄+性别+交费期），输入用户问题"""
    docs = await rate_table_retriever.ainvoke(question)
    return "\n".join(d.page_content for d in docs) or "未命中费率表行"


@tool
async def search_products(question: str) -> str:
    """检索平台在售产品候选，输入用户问题"""
    docs = await product_retriever.ainvoke(question)
    return "\n".join(
        f"- {d.metadata['name']}（承保公司：{d.metadata['insurer']}）{d.metadata['description']}"
        for d in docs
    ) or "未匹配到产品"
