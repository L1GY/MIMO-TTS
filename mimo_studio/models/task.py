"""合成任务模型：任务状态持久化，前端轮询这张表即可。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.base import TimestampMixin, new_id, now

# 任务状态机：queued → running → success / failed
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

STATUS_TEXT = {
    STATUS_QUEUED: "排队中",
    STATUS_RUNNING: "生成中",
    STATUS_SUCCESS: "已完成",
    STATUS_FAILED: "失败",
}


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voice_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 冗余保存，避免音色被删除后历史记录无法展示
    voice_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    voice_kind: Mapped[str] = mapped_column(String(16), default="preset", nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_len: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    speed: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=STATUS_QUEUED, nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)       # 0-100
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    result_path: Mapped[str | None] = mapped_column(String(255), nullable=True)     # 相对 static
    result_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner = relationship("User", back_populates="tasks")

    # ------------------------------------------------------------ 便捷属性
    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    @property
    def audio_url(self) -> str | None:
        if self.status == STATUS_SUCCESS and self.result_path:
            return f"/static/{self.result_path}"
        return None

    @property
    def text_brief(self) -> str:
        one_line = " ".join((self.text or "").split())
        return one_line[:60] + ("…" if len(one_line) > 60 else "")

    @property
    def size_text(self) -> str:
        if not self.result_size:
            return "—"
        mb = self.result_size / 1024 / 1024
        return f"{mb:.2f} MB" if mb >= 1 else f"{self.result_size / 1024:.0f} KB"

    @property
    def duration_text(self) -> str:
        if not self.duration:
            return "—"
        sec = int(self.duration)
        return f"{sec // 60}:{sec % 60:02d}"

    @property
    def elapsed_text(self) -> str:
        if not self.started_at or not self.finished_at:
            return "—"
        return f"{(self.finished_at - self.started_at).total_seconds():.1f}s"

    def mark_running(self) -> None:
        self.status = STATUS_RUNNING
        self.started_at = now()
        self.progress = 3

    def mark_failed(self, message: str) -> None:
        self.status = STATUS_FAILED
        self.error = message[:1000]
        self.finished_at = now()
