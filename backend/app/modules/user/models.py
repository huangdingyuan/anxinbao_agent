"""用户模块

复用数据库已有 users 表，提供个人资料查看/编辑能力（JWT 认证，按令牌中的用户 ID 定位用户）。
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class User(Base, CreateAtMixin, UpdateAtMixin):
    """用户"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    # 不对外暴露，仅占位保证 ORM 完整映射
    password_hash: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # active 正常 / disabled 禁用
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    # 手机号（迁移新增列，可为空）
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
