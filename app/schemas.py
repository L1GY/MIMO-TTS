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

    # 界面上的合成参数。上游不直接支持，由服务端对返回的 PCM 做后处理实现。
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速倍率，0.5～2")
    pitch: float = Field(default=0.0, ge=-12.0, le=12.0, description="音调，单位为半音")
    sample_rate: int | None = Field(default=None, description="输出采样率，如 16000 / 24000 / 44100")

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


# ------------------------------------------------------------------ TTS 试听


class TTSPreviewRequest(BaseModel):
    """音色一键试听：短文本、小体积，结果以 data URL 直接返回，不落库、不落盘。"""

    voice: str | None = Field(default=None, description="预置音色 ID")
    voice_desc: str | None = Field(default=None, description="音色设计描述")
    voice_preset_id: str | None = Field(default=None, description="已保存的自定义音色 ID")
    text: str = Field(default="你好，这是音色试听示例。", max_length=200)
    audio_format: str = Field(default="wav", description="wav / mp3 / pcm16")

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("试听文本不能为空")
        return v

    @field_validator("audio_format")
    @classmethod
    def _check_format(cls, v: str) -> str:
        v = (v or "wav").lower()
        if v not in {"wav", "mp3", "pcm", "pcm16"}:
            raise ValueError("audio_format 仅支持 wav / mp3 / pcm / pcm16")
        return v


# ------------------------------------------------------------------ ASR


class ASRTranscribeResponse(BaseModel):
    id: str
    transcript: str
    segments: list[str] | None = None
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
