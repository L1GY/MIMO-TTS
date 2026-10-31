"""操作日志：记录用户每一次提交、删除、修改，管理员可追溯。"""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.base import TimestampMixin, new_id


class OpLog(Base, TimestampMixin):
    __tablename__ = "op_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(32), default="", nullable=False)  # 冗余，账号删除后仍可追溯
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)   # 如 tts.submit
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner = relationship("User")
