"""LangGraph Agent 运行时生命周期

psycopg AsyncConnectionPool + AsyncPostgresSaver checkpointer + 编译图单例。
初始化失败（DB 不可达等）时图单例保持 None，chat service 自动回退 legacy 直连路径。
"""

from pydantic import PostgresDsn

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_pool = None  # psycopg AsyncConnectionPool
_saver = None  # AsyncPostgresSaver
_graph = None  # 编译后的保险顾问图；None 表示 Agent 不可用，service 走 legacy 回退


def psycopg_dsn() -> str:
    """从数据库配置重建 psycopg 格式 DSN（settings.db.url 是 asyncpg 格式，不可直接用）"""
    db = settings.db
    return PostgresDsn.build(
        scheme="postgresql",
        host=db.host,
        port=db.port,
        username=db.user,
        password=db.password,
        path=db.name,
    ).encoded_string()


async def init_agent_runtime() -> None:
    """建池、建 checkpoint 表（setup 幂等）、编译图。任何异常向上抛，由调用方降级。"""
    global _pool, _saver, _graph
    if not settings.agent.enabled:
        logger.info("CHAT_AGENT_ENABLED=false，Agent runtime 不启用（走 legacy 直连 LLM 路径）")
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    from app.modules.chat.agent import build_advisor_graph

    _pool = AsyncConnectionPool(
        conninfo=psycopg_dsn(),
        min_size=1,
        max_size=4,
        open=False,
        # checkpointer 官方硬性要求：autocommit + 禁用预编译语句缓存
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await _pool.open(wait=True)
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()  # 幂等创建 checkpoints/checkpoint_blobs/checkpoint_writes/checkpoint_migrations
    _graph = build_advisor_graph(checkpointer=_saver)
    logger.info("LangGraph Agent runtime 初始化完成 ✅（checkpointer=Postgres, thread_id=chat_threads.id）")


async def close_agent_runtime() -> None:
    global _pool, _saver, _graph
    if _pool is not None:
        await _pool.close()
        logger.info("Agent runtime 连接池已关闭~")
    _pool = _saver = _graph = None


def get_advisor_graph():
    """图单例；None 表示 Agent 不可用（未启用或初始化失败），调用方须回退 legacy"""
    return _graph
