"""公共工具函数。"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


def verify_password(plain: str, password_hash: str) -> bool:
    """bcrypt 校验；占位/非法哈希一律返回 False"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(user_id: int) -> str:
    """签发 JWT 访问令牌（HS256），sub 为用户 ID"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.auth.expire_minutes),
    }
    return jwt.encode(payload, settings.auth.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> int:
    """解析并校验 JWT，返回用户 ID；签名/过期/格式非法统一抛 401"""
    try:
        payload = jwt.decode(token, settings.auth.secret_key, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise UnauthorizedError("登录凭证无效或已过期，请重新登录")
