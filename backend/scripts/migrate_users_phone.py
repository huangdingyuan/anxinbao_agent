import asyncio
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.common.database import engine


async def main():
    """users 表新增 phone 列（幂等）"""
    async with engine.begin() as conn:
        exists = await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='phone'"
        ))
        if exists.scalar_one_or_none() is None:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN phone VARCHAR(40) NULL"
            ))
            print("已添加 users.phone 列")
        else:
            print("users.phone 列已存在，跳过")


asyncio.run(main())
