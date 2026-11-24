import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect(
        user="insurance",
        password="insurance123",
        database="insurance",
        host="127.0.0.1",
        port=5432,
        ssl=False
    )
    print("数据库连接成功！")
    await conn.close()

asyncio.run(main())
