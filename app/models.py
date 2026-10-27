"""ORM 模型：用户、自定义音色、TTS 调用历史、ASR 调用历史。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 微信身份（可配置登录方式使用，未配置时留空）
    wechat_openid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    wechat_unionid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tts_records: Mapped[list["TTSRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    asr_records: Mapped[list["ASRRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    voice_presets: Mapped[list["VoicePreset"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "nickname": self.nickname or self.username,
            "wechat_bound": bool(self.wechat_openid),
            "created_at": self.created_at.isoformat() + "Z",
        }


class VoicePreset(Base):
    """用户设计并保存的音色。"""

    __tablename__ = "voice_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)  # 音色描述，合成时作为提示
    # 设计音色时使用的试听样本文本，方便复现
    sample_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 卡片标识色

    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="voice_presets", lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "sample_text": self.sample_text,
            "color": self.color,
            "use_count": self.use_count,
            "created_at": self.created_at.isoformat() + "Z",
            "last_used_at": (self.last_used_at.isoformat() + "Z") if self.last_used_at else None,
        }


class TTSRecord(Base):
    """一次文本转语音调用。"""

    __tablename__ = "tts_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 请求参数
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    voice: Mapped[str | None] = mapped_column(String(128), nullable=True)    # 预置音色 ID
    voice_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 音色展示名
    voice_desc: Mapped[str | None] = mapped_column(Text, nullable=True)      # 音色设计描述
    voice_preset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 关联自定义音色
    audio_format: Mapped[str] = mapped_column(String(16), default="wav", nullable=False)
    optimize_text: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    text_input: Mapped[str] = mapped_column(Text, nullable=False)

    # 结果
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    text_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audio_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audio_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 计量
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="tts_records", lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "tts",
            "model": self.model,
            "voice": self.voice,
            "voice_name": self.voice_name,
            "voice_desc": self.voice_desc,
            "voice_preset_id": self.voice_preset_id,
            "audio_format": self.audio_format,
            "optimize_text": self.optimize_text,
            "text_input": self.text_input,
            "text_final": self.text_final,
            "status": self.status,
            "audio_size": self.audio_size,
            "audio_mime": self.audio_mime,
            "has_audio": bool(self.audio_path),
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() + "Z",
        }


class ASRRecord(Base):
    """一次语音识别调用。"""

    __tablename__ = "asr_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    model: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)

    stored_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="asr_records", lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "asr",
            "model": self.model,
            "language": self.language,
            "filename": self.filename,
            "file_size": self.file_size,
            "file_mime": self.file_mime,
            "has_audio": bool(self.stored_path),
            "status": self.status,
            "transcript": self.transcript,
            "audio_seconds": self.audio_seconds,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() + "Z",
        }
