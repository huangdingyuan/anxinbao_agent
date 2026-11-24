"""迁移脚本：重置种子用户密码为 bcrypt("123456")（幂等可重复执行）"""
import asyncio
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.common.database import engine
from app.common.utils import hash_password


async def main():
    async with engine.begin() as conn:
        result = await conn.execute(
            text("UPDATE users SET password_hash = :h WHERE username = 'demo'"),
            {"h": hash_password("123456")},
        )
        print(f"已重置 demo 用户密码为 123456（bcrypt），更新行数: {result.rowcount}")


asyncio.run(main())
