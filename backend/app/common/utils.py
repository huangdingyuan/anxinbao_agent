"""公共工具函数。"""

import bcrypt


def verify_password(plain: str, password_hash: str) -> bool:
    """bcrypt 校验；占位/非法哈希一律返回 False"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
