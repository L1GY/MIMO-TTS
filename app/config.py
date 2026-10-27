"""全局配置。

配置优先级：系统环境变量 > .env 文件 > 本文件中的默认值。
敏感信息（上游密钥、JWT 密钥、微信密钥）只从环境变量 / .env 读取，不硬编码在代码中。
上游协议所需的模型 ID、音色 ID 同样全部外置到 .env，源码中不留任何上游品牌字面量。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent

log = logging.getLogger("voice_atelier.config")

APP_NAME = "声坊"
APP_NAME_EN = "Voice Atelier"

# 上游协议所需但缺失时给出清晰提示，避免静默失败
REQUIRED_UPSTREAM_KEYS = ("tts_model", "tts_model_design", "tts_model_clone", "asr_model", "tts_default_voice")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 上游语音服务平台 ----------------
    speech_api_key: str = Field(default="", description="上游语音服务 API Key")
    speech_api_base_url: str = Field(default="")
    tts_model: str = Field(default="", description="预置音色合成模型 ID")
    tts_model_design: str = Field(default="", description="音色设计模型 ID")
    tts_model_clone: str = Field(default="", description="音色克隆模型 ID")
    asr_model: str = Field(default="", description="语音识别模型 ID")
    tts_default_voice: str = Field(default="", description="默认预置音色 ID")
    tts_preset_voices: str = Field(default="[]", description="预置音色列表，JSON 数组")

    speech_timeout: float = Field(default=120.0, description="上游请求超时（秒）")
    speech_max_retries: int = Field(default=2, description="可重试错误的最大重试次数")

    # 无密钥时的本地模拟模式，保证应用开箱可运行
    mock_mode: bool = Field(default=True)

    # ---------------- 安全 ----------------
    jwt_secret: str = Field(default="dev-only-secret-please-change-me")
    jwt_expire_minutes: int = Field(default=720)

    # ---------------- 存储 ----------------
    database_url: str = Field(default=f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
    audio_dir: str = Field(default=str(BASE_DIR / "data" / "audio"))
    upload_dir: str = Field(default=str(BASE_DIR / "data" / "uploads"))

    # ---------------- 业务限制 ----------------
    max_upload_mb: int = Field(default=7)
    max_text_length: int = Field(default=2000)

    # ---------------- 服务 ----------------
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    cors_origins: str = Field(default="http://127.0.0.1:8000,http://localhost:8000")

    # ---------------- 微信扫码登录（可选）----------------
    wechat_app_id: str = Field(default="")
    wechat_app_secret: str = Field(default="")
    wechat_redirect_uri: str = Field(default="http://127.0.0.1:8000/api/auth/wechat/callback")

    # ---------------- 派生属性 ----------------
    @property
    def chat_completions_url(self) -> str:
        return f"{self.speech_api_base_url.rstrip('/')}/chat/completions"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def wechat_enabled(self) -> bool:
        """微信登录是否可用：仅当 AppID 与 AppSecret 均已配置。"""
        return bool(self.wechat_app_id and self.wechat_app_secret)

    @property
    def live_mode(self) -> bool:
        """是否真正调用上游语音服务。"""
        return bool(self.speech_api_key) and not self.mock_mode

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def upstream_ready(self) -> tuple[bool, list[str]]:
        """检查上游必需配置是否齐全，返回 (是否齐全, 缺失项列表)。"""
        missing = [k for k in REQUIRED_UPSTREAM_KEYS if not getattr(self, k)]
        if not self.speech_api_base_url:
            missing.append("speech_api_base_url")
        return (not missing), missing


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def preset_voices() -> list[dict[str, str]]:
    """解析预置音色列表（来自 .env 中的 TTS_PRESET_VOICES）。"""
    try:
        data = json.loads(settings.tts_preset_voices or "[]")
        if isinstance(data, list):
            return [v for v in data if isinstance(v, dict) and v.get("id")]
    except Exception as exc:  # noqa: BLE001
        log.warning("预置音色配置解析失败（TTS_PRESET_VOICES 不是合法 JSON）：%s", exc)
    return []


def voice_display_name(voice_id: str | None) -> str | None:
    """把预置音色 ID 映射为展示名。"""
    if not voice_id:
        return None
    for v in preset_voices():
        if v.get("id") == voice_id:
            return v.get("name") or voice_id
    return voice_id


# TTS 输出格式（audio.format 可选值）
TTS_FORMATS: list[dict[str, str]] = [
    {"id": "wav", "name": "WAV", "mime": "audio/wav", "ext": "wav"},
    {"id": "mp3", "name": "MP3", "mime": "audio/mpeg", "ext": "mp3"},
]

# 语音识别输入音频格式（上游仅支持 wav / mp3）
ASR_INPUT_FORMATS: dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}

# 识别语种（asr_options.language 可选值）
ASR_LANGUAGES: list[dict[str, str]] = [
    {"id": "auto", "name": "自动检测"},
    {"id": "zh", "name": "中文"},
    {"id": "en", "name": "英文"},
]
