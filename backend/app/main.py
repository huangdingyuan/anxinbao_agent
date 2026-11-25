from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
import uvicorn

# 初始化日志系统
configure_logging(settings.logging.level)
logger = get_logger(__name__)
from contextlib import asynccontextmanager

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"【{settings.app.name}】应用启动中...")
    from app.common.database import check_database, close_database
    from app.core.agent_runtime import close_agent_runtime, init_agent_runtime
    try:
        await check_database()
    except Exception:
        logger.exception("数据库不可用，应用无法启动")
        raise
    try:
        await init_agent_runtime()
    except Exception:
        # Agent runtime 失败不阻断启动：图单例保持 None，问答自动回退 legacy 直连路径
        logger.exception("Agent runtime 初始化失败，回退 legacy 直连 LLM 模式")
    try:
        yield
    finally:
        logger.info("应用关闭中... ")
        await close_agent_runtime()
        await close_database()
app = FastAPI(
    title=settings.app.name,
    debug=settings.app.debug,
    lifespan=lifespan,
)
from app.core.exceptions import register_exception_handlers

# 注册全局异常处理器，统一错误响应格式
register_exception_handlers(app)
from app.modules.products.router import router as product_router

# 创建 app 后注册路由
app.include_router(product_router)
from app.modules.conversation.router import router as conversation_router

app.include_router(conversation_router)
from app.modules.chat.router import router as chat_router, frontend_router as chat_frontend_router

app.include_router(chat_router)
app.include_router(chat_frontend_router)
from app.modules.insurance_plan.router import router as insurance_plan_router

app.include_router(insurance_plan_router)
from app.modules.policy.router import router as policy_router

app.include_router(policy_router)
from app.modules.claim.router import router as claim_router

app.include_router(claim_router)
from app.modules.knowledge.router import router as knowledge_router

app.include_router(knowledge_router)
from app.modules.user.router import router as user_router, auth_router as user_auth_router

app.include_router(user_router)
app.include_router(user_auth_router)

@app.get("/health", summary="健康检测接口")
async def health_check() -> dict[str, str]:
    logger.info("执行健康检查")
    return {"status": "ok"}


if __name__ == "__main__":
    import asyncio
    import sys

    config = uvicorn.Config(
        "app.main:app",
        host=settings.app.host,
        port=settings.app.port,
        reload=False,
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        # psycopg 异步模式（LangGraph checkpointer）要求 Selector 事件循环，
        # Windows 默认 Proactor 不可用；Python 3.14 起 policy 已弃用，直接 loop_factory
        import selectors

        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(server.serve())