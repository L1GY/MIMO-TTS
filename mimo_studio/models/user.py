"""用户模型。密码使用 bcrypt 哈希，角色分为 user / admin。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.base import TimestampMixin, new_id, now


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(120), nullable=False)

    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # user / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 额度按「字符」计算：每次合成扣除文本长度，失败自动退回
    quota_chars: Mapped[int] = mapped_column(Integer, default=20000, nullable=False)
    used_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    voices = relationship("Voice", back_populates="owner", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="owner", cascade="all, delete-orphan")

    # ------------------------------------------------------------ 便捷属性
    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def quota_left(self) -> int:
        return max(0, int(self.quota_chars) - int(self.used_chars))

    @property
    def quota_percent(self) -> int:
        if self.quota_chars <= 0:
            return 100
        return max(0, min(100, round(self.quota_left / self.quota_chars * 100)))

    @property
    def initial(self) -> str:
        return (self.username or "?")[0].upper()

    def touch_login(self) -> None:
        self.last_login_at = now()
