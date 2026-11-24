"""全量同步脚本：PostgreSQL kb_chunks 向量 → Milvus collection（幂等，可重复执行）"""
import asyncio
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sqlalchemy import select

from app.common import milvus
from app.modules.knowledge.models import KbChunk, KbDocument
from app.modules.knowledge.embedder import _get_model

from app.common.database import AsyncSessionFactory

BATCH = 500


async def main() -> None:
    if _get_model() is None:
        print("向量模型不可用，先跑 parse_kb.py backfill")
        return
    client = milvus._get_client()
    if client is None:
        print("Milvus 不可用（检查 MILVUS_URI 与 Docker 服务）")
        return
    # --rebuild: 先清空 collection 重建（混用 insert/upsert 后有脏数据时使用）
    if "--rebuild" in sys.argv:
        name = settings.milvus.collection
        client.drop_collection(name)
        milvus.reset_state()
        client = milvus._get_client()
        print(f"已重建 collection: {name}")

    async with AsyncSessionFactory() as session:
        # 全部带向量块 + 关联文档信息
        result = await session.execute(
            select(KbChunk, KbDocument)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
            .where(KbChunk.embedding.is_not(None))
        )
        pairs = result.all()

    print(f"待同步 {len(pairs)} 块")
    total = 0
    for i in range(0, len(pairs), BATCH):
        rows = []
        for chunk, doc in pairs[i:i + BATCH]:
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
        total += len(rows)
        print(f"  已写入 {total}/{len(pairs)}")

    client.flush(collection_name=settings.milvus.collection)  # 强制落盘，stats 才准确
    stats = milvus.count()
    print(f"同步完成 ✅ Milvus row_count={stats} / collection: {settings.milvus.collection}")


if __name__ == "__main__":
    from app.core.config import settings
    print(f"Milvus: {settings.milvus.uri} / collection: {settings.milvus.collection}")
    asyncio.run(main())
