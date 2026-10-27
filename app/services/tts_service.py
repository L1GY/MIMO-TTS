"""文本转语音（TTS）服务。

上游接口要点：
  · 三类模型：预置音色 / 音色设计 / 音色克隆，模型 ID 全部来自 .env 配置
  · 生成音频必须携带一条 role=assistant 的消息，其 content 为待合成文本
  · audio.voice：预置音色 ID 或克隆样本的 base64；音色设计模型不支持该字段
  · audio.format：wav（默认）/ mp3 / pcm16
  · audio.optimize_text_preview：播报文本智能优化，仅音色设计模型支持
  · 音频在 choices[0].message.audio.data 中以 base64 返回
"""

from __future__ import annotations

import base64
import logging
import math
import struct
import wave
from io import BytesIO
from typing import Any

from ..config import settings
from . import speech_client

log = logging.getLogger("voice_atelier.tts")

MIME_BY_FORMAT = {
    "wav": ("audio/wav", "wav"),
    "mp3": ("audio/mpeg", "mp3"),
    "pcm": ("audio/wav", "wav"),
    "pcm16": ("audio/wav", "wav"),
}

# 裸 pcm16 落盘为 wav 时的假设采样率（上游未公开，可在配置中按需调整）
PCM_ASSUMED_RATE = 24000


def is_design_model(model: str) -> bool:
    return bool(settings.tts_model_design) and model == settings.tts_model_design


def is_clone_model(model: str) -> bool:
    return bool(settings.tts_model_clone) and model == settings.tts_model_clone


def build_payload(
    *,
    model: str,
    text: str,
    voice: str | None = None,
    voice_desc: str | None = None,
    audio_format: str = "wav",
    optimize_text: bool = False,
    clone_sample_base64: str | None = None,
) -> dict[str, Any]:
    """按模型类型组装请求体。"""
    messages: list[dict[str, Any]] = []

    if is_design_model(model):
        # user 消息为音色设计描述（必填）
        design = (voice_desc or "").strip() or "自然、清晰的播报音色"
        messages.append({"role": "user", "content": design})
    elif is_clone_model(model):
        messages.append({"role": "user", "content": voice_desc or "请参照该音色朗读下方文本"})

    # assistant 消息指定合成文本
    messages.append({"role": "assistant", "content": text})

    audio: dict[str, Any] = {"format": "pcm16" if audio_format in ("pcm", "pcm16") else audio_format}

    if model == settings.tts_model:
        audio["voice"] = (voice or settings.tts_default_voice).strip() or settings.tts_default_voice
    elif is_clone_model(model):
        audio["voice"] = clone_sample_base64  # 必填，样本音频 base64

    if optimize_text and is_design_model(model):
        audio["optimize_text_preview"] = True

    return {"model": model, "messages": messages, "audio": audio}


def _parse_response(data: dict[str, Any]) -> tuple[bytes, str | None, str | None, dict[str, Any]]:
    """从 chat.completion 响应中取出音频。

    返回 (audio_bytes, upstream_audio_id, final_text_preview, usage)
    """
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        from ..errors import UpstreamError

        raise UpstreamError(
            "上游返回内容中没有可用的音频数据",
            code="upstream_bad_response",
            detail=str(data)[:500],
        ) from exc

    audio_obj = message.get("audio") or {}
    b64 = audio_obj.get("data")
    if not b64:
        from ..errors import UpstreamError

        raise UpstreamError(
            "上游未返回音频（可能文本被内容安全策略拦截），请修改文本后重试",
            code="empty_audio",
            detail=(message.get("content") or "")[:300],
        )

    try:
        raw = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        from ..errors import UpstreamError

        raise UpstreamError("音频 base64 解码失败", code="upstream_bad_response") from exc

    usage = data.get("usage") or {}
    return raw, audio_obj.get("id"), message.get("final_text_preview"), usage


def _pcm16_to_wav(pcm: bytes, sample_rate: int = PCM_ASSUMED_RATE) -> bytes:
    """把裸 pcm16 包一层 WAV 头，便于浏览器直接播放。"""
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _mock_wav(text: str) -> bytes:
    """模拟模式下生成一段本地 WAV 提示音，让全链路无需密钥即可跑通。"""
    duration = min(8.0, max(1.2, len(text) / 14.0))
    rate = 22050
    frames = int(duration * rate)
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            t = i / rate
            envelope = 0.35 * (0.6 + 0.4 * math.sin(2 * math.pi * 0.7 * t))
            sample = 0.5 * math.sin(2 * math.pi * 320 * t) + 0.3 * math.sin(2 * math.pi * 480 * t)
            value = int(max(-1.0, min(1.0, sample)) * envelope * 32767)
            data += struct.pack("<h", value)
        w.writeframes(bytes(data))
    return buf.getvalue()


async def synthesize(
    *,
    text: str,
    model: str | None = None,
    voice: str | None = None,
    voice_desc: str | None = None,
    audio_format: str = "wav",
    optimize_text: bool = False,
    clone_sample_base64: str | None = None,
) -> dict[str, Any]:
    """执行一次合成。

    返回 dict：audio_bytes, mime, ext, text_final, audio_id, usage, request_id, is_mock, model
    """
    model = model or settings.tts_model
    request_id: str | None = None

    if is_clone_model(model) and not clone_sample_base64:
        from ..errors import AppError

        raise AppError("音色克隆模式必须提供参考音频样本", code="missing_clone_sample")

    if settings.live_mode:
        payload = build_payload(
            model=model,
            text=text,
            voice=voice,
            voice_desc=voice_desc,
            audio_format=audio_format,
            optimize_text=optimize_text,
            clone_sample_base64=clone_sample_base64,
        )
        data = await speech_client.chat_completions(payload)
        raw, audio_id, preview, usage = _parse_response(data)
        request_id = data.get("id")
        is_mock = False
    else:
        log.info("模拟模式：生成本地占位音频（未调用上游）")
        raw = _mock_wav(text)
        audio_id, preview, usage = None, None, {}
        is_mock = True
        if audio_format in ("mp3",):
            # 模拟模式不引入音频编码器，统一回退为 wav
            audio_format = "wav"

    if audio_format in ("pcm", "pcm16"):
        raw = _pcm16_to_wav(raw)
        audio_format = "wav"

    mime, ext = MIME_BY_FORMAT.get(audio_format, ("audio/wav", "wav"))

    return {
        "audio_bytes": raw,
        "mime": mime,
        "ext": ext,
        "text_final": preview or text,
        "audio_id": audio_id,
        "usage": usage,
        "request_id": request_id,
        "is_mock": is_mock,
        "model": model,
    }
