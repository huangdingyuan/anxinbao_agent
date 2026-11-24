"""业务异常定义与全局异常处理器。

自定义异常统一继承 BizError，由 register_exception_handlers 注册的
全局处理器转换为统一格式的 JSON 响应：
    {"code": 状态码, "message": "错误描述", "details": [可选的详情列表]}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class BizError(Exception):
    """业务异常基类"""

    status_code: int = 400
    default_message: str = "业务处理失败"

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(BizError):
    """资源不存在"""

    status_code = 404
    default_message = "资源不存在"


class UnauthorizedError(BizError):
    """认证失败"""

    status_code = 401
    default_message = "登录认证失败"


class PermissionDeniedError(BizError):
    """无权访问该资源"""

    status_code = 403
    default_message = "无权访问该资源"


def _error_body(code: int, message: str, details: list | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if details:
        body["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册全局异常处理器"""

    # 1. 请求参数校验失败（Pydantic）
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(loc) for loc in err["loc"][1:]),  # 跳过 body/query 等位置前缀
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(422, "请求参数校验失败", details),
        )

    # 2. HTTPException（如 404 路由不存在、接口内主动 raise 的 HTTPException）
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.status_code, str(exc.detail)),
        )

    # 3. 业务异常
    @app.exception_handler(BizError)
    async def biz_error_handler(request: Request, exc: BizError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.status_code, exc.message),
        )

    # 4. 兜底：未捕获异常，记录完整堆栈，对外只返回通用提示。
    #    用 HTTP 中间件而非 @app.exception_handler(Exception)，
    #    因为 debug 模式下 ServerErrorMiddleware 会忽略后者，返回空响应。
    @app.middleware("http")
    async def unhandled_exception_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception(f"未处理异常 {request.method} {request.url.path}: {exc!r}")
            return JSONResponse(
                status_code=500,
                content=_error_body(500, "服务器内部错误，请稍后重试"),
            )
