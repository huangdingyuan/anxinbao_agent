"""Milvus 向量数据库客户端

管理知识库向量 collection 的生命周期：幂等建表、批量插入、按文档删除、
相似度检索。Milvus 不可用时由上层自动降级为内存余弦检索。
"""

from __future__ import annotations

import threading

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 查询返回时需要带出的标量字段
OUTPUT_FIELDS = [
    "chunk_id", "document_id", "category", "source_name",
    "product_name", "page_no", "heading", "content",
]

_lock = threading.Lock()
_client = None  # MilvusClient 单例
_ready = False  # collection 是否已确认存在
_init_failed = False  # 初始化失败标记，避免每次请求重复连接


def _get_client():
    """懒加载 MilvusClient 单例并确保 collection 存在；失败返回 None"""
    global _client, _ready, _init_failed
    if not settings.milvus.enabled or _init_failed:
        return None
    with _lock:
        if _client is not None and _ready:
            return _client
        if _init_failed:
            return None
        try:
            from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

            client = MilvusClient(uri=settings.milvus.uri)
            name = settings.milvus.collection
            if not client.has_collection(name):
                # bge-small-zh-v1.5 输出 512 维，向量已归一化，COSINE 度量
                schema = CollectionSchema(
                    fields=[
                        FieldSchema("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64),
                        FieldSchema("document_id", DataType.VARCHAR, max_length=64),
                        FieldSchema("category", DataType.VARCHAR, max_length=32),
                        FieldSchema("source_name", DataType.VARCHAR, max_length=256),
                        FieldSchema("product_name", DataType.VARCHAR, max_length=256),
                        FieldSchema("page_no", DataType.INT64),
                        FieldSchema("heading", DataType.VARCHAR, max_length=256),
                        FieldSchema("content", DataType.VARCHAR, max_length=65535),
                        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=512),
                    ],
                    description="知识库切块向量（关键词检索仍在 PostgreSQL，本库只做语义路）",
                )
                index_params = client.prepare_index_params()
                index_params.add_index(
                    field_name="embedding",
                    index_type="HNSW",
                    metric_type="COSINE",
                    params={"M": 16, "efConstruction": 200},
                )
                client.create_collection(
                    collection_name=name, schema=schema, index_params=index_params
                )
                logger.info(f"Milvus collection 已创建: {name}")
            _client = client
            _ready = True
            logger.info("Milvus 连接成功 ✅")
        except Exception as exc:
            _init_failed = True
            logger.warning(f"Milvus 初始化失败，语义检索降级内存余弦: {exc!r}")
        return _client


def reset_state() -> None:
    """重置连接状态（同步脚本重连时使用）"""
    global _client, _ready, _init_failed
    with _lock:
        _client = None
        _ready = False
        _init_failed = False


def upsert_chunks(rows: list[dict]) -> int:
    """批量写入/更新向量（chunk_id 为主键，重复执行幂等覆盖），返回写入条数"""
    client = _get_client()
    if client is None or not rows:
        return 0
    client.upsert(collection_name=settings.milvus.collection, data=rows)
    return len(rows)


def delete_by_document(document_id: str) -> None:
    """删除指定文档的全部向量（重新入库前调用）"""
    client = _get_client()
    if client is None:
        return
    client.delete(
        collection_name=settings.milvus.collection,
        filter=f'document_id == "{document_id}"',
    )


def search_similar(query_vec: np.ndarray, top_n: int) -> list[dict]:
    """余弦相似度检索，返回 [{chunk_id, similarity, ...标量字段}] 按相似度降序"""
    client = _get_client()
    if client is None:
        return []
    results = client.search(
        collection_name=settings.milvus.collection,
        data=[query_vec.tolist()],
        limit=top_n,
        output_fields=OUTPUT_FIELDS,
        search_params={"metric_type": "COSINE"},
    )[0]
    return [
        {
            "chunk_id": hit["entity"]["chunk_id"],
            "similarity": float(hit["distance"]),
            **{k: hit["entity"][k] for k in OUTPUT_FIELDS if k != "chunk_id"},
        }
        for hit in results
    ]


def count() -> int:
    """collection 内向量总数（-1 表示不可用）"""
    client = _get_client()
    if client is None:
        return -1
    return client.get_collection_stats(settings.milvus.collection)["row_count"]
