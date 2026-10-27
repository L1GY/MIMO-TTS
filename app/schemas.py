"""Pydantic 请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ 鉴权


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    email: str | None = Field(default=None, max_length=255)
    nickname: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserOut(BaseModel):
    id: str
    username: str
    email: str | None = None
    nickname: str
    wechat_bound: bool = False
    created_at: str


# ------------------------------------------------------------------ TTS


class TTSSynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, description="待合成文本")
    model: str | None = Field(default=None, description="覆盖默认合成模型")
    voice: str | None = Field(default=None, description="预置音色 ID")
    voice_desc: str | None = Field(default=None, description="音色设计描述")
    voice_preset_id: str | None = Field(default=None, description="已保存的自定义音色 ID")
    audio_format: str = Field(default="wav", description="wav / mp3 / pcm16")
    optimize_text: bool = Field(default=False, description="是否开启播报文本智能优化")
    clone_sample_base64: str | None = Field(default=None, description="音色克隆样本音频 base64")

    @field_validator("audio_format")
    @classmethod
    def _check_format(cls, v: str) -> str:
        v = (v or "wav").lower()
        if v not in {"wav", "mp3", "pcm", "pcm16"}:
            raise ValueError("audio_format 仅支持 wav / mp3 / pcm / pcm16")
        return v

    @field_validator("text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("合成文本不能为空")
        return v


# ------------------------------------------------------------------ ASR


class ASRTranscribeResponse(BaseModel):
    id: str
    transcript: str
    model: str
    language: str
    audio_seconds: float | None = None
    latency_ms: int | None = None
    usage: dict | None = None
    request_id: str | None = None
    filename: str | None = None
    created_at: str


# ------------------------------------------------------------------ 通用


class HistoryPage(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int
