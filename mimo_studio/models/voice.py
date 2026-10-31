"""音色模型。

两种类型：
  preset —— MiMo 官方预置音色（user_id 为空，voice_key 是官方音色标识）
  clone  —— 用户上传参考音频形成的克隆音色（sample_path 指向本地样本文件）

MiMo 的克隆机制是「每次合成直接传参考音频」，所以这里不需要任何「创建音色」的远程调用，
上传成功即完成音色创建。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.base import TimestampMixin, new_id


class Voice(Base, TimestampMixin):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    kind: Mapped[str] = mapped_column(String(16), default="clone", nullable=False)  # preset / clone
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    desc: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # preset 专用：官方音色标识（如 冰糖 / Mia / mimo_default）
    voice_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # clone 专用：参考音频
    sample_path: Mapped[str | None] = mapped_column(String(255), nullable=True)   # 相对 static 的路径
    sample_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 字节
    sample_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 声音授权留痕（必须勾选才能创建）
    consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 管理员可强制下架
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active / blocked
    blocked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    owner = relationship("User", back_populates="voices")

    @property
    def sample_url(self) -> str | None:
        """样本音频的静态访问地址。"""
        if self.kind == "clone" and self.sample_path:
            return f"/static/{self.sample_path}"
        return None

    @property
    def size_text(self) -> str:
        if not self.sample_size:
            return "—"
        mb = self.sample_size / 1024 / 1024
        if mb >= 1:
            return f"{mb:.1f} MB"
        return f"{self.sample_size / 1024:.0f} KB"

    @property
    def duration_text(self) -> str:
        if not self.sample_seconds:
            return "—"
        return f"{float(self.sample_seconds):.1f}s"
