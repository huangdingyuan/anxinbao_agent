"""迁移脚本：kb_chunks 表新增 embedding 向量列（幂等）"""
import asyncio
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.common.database import engine


async def main():
    async with engine.begin() as conn:
        exists = await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='kb_chunks' AND column_name='embedding'"
        ))
        if exists.scalar_one_or_none() is None:
            await conn.execute(text(
                "ALTER TABLE kb_chunks ADD COLUMN embedding BYTEA NULL"
            ))
            print("已添加 kb_chunks.embedding 列")
        else:
            print("kb_chunks.embedding 列已存在，跳过")


asyncio.run(main())
