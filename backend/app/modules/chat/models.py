from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin

# 显式导入外键目标表的模型，确保同一 Base.metadata 完整注册，
# 避免独立脚本/部分导入场景下 flush 时抛 NoReferencedTableError
import app.modules.conversation.models  # noqa: F401,E402
import app.modules.products.models  # noqa: F401,E402
import app.modules.insurance_plan.models  # noqa: F401,E402
import app.modules.policy.models  # noqa: F401,E402
import app.modules.claim.models  # noqa: F401,E402
import app.modules.knowledge.models  # noqa: F401,E402


class ChatMessage(Base, CreateAtMixin):
    """会话消息，问答记录"""

    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    # 所属会话，会话删除时级联删除消息
    thread_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
    )
    # 消息角色：user 提问 / assistant 回答
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # 回答附带的附加信息（参考产品等），仅 assistant 消息使用
    additional_info: Mapped[list | None] = mapped_column(JSONB, nullable=True)
