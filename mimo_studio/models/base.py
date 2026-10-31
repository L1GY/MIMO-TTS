"""模型公共部分。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def new_id() -> str:
    """短 ID：时间戳前缀 + 随机后缀，便于排序与排查。"""
    return uuid.uuid4().hex[:16]


def now() -> datetime:
    """统一使用本地时间，页面上直接展示，无需再做时区换算。"""
    return datetime.now()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False, index=True)
