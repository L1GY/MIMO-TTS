"""语音识别（ASR）服务。

上游接口要点：
  · 模型 ID 来自 .env 的 ASR_MODEL
  · 输入音频仅支持 wav / mp3
  · 传入方式：data URL（data:{MIME};base64,xxx）或纯 base64（此时 format 必填）
  · base64 编码后大小上限 10MB
  · asr_options.language：auto / zh / en
  · 识别结果在 choices[0].message.content，音频时长在 usage.seconds
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from ..config import ASR_INPUT_FORMATS, settings
from . import speech_client

log = logging.getLogger("voice_atelier.asr")


def build_payload(*, model: str, audio_b64: str, mime: str, fmt: str, language: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        # data URL 与 format 同时给出，二者取值保持一致
                        "input_audio": {"data": f"data:{mime};base64,{audio_b64}", "format": fmt},
                    }
                ],
            }
        ],
        "asr_options": {"language": language or "auto"},
    }


def _parse_response(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        from ..errors import UpstreamError

        raise UpstreamError(
            "上游返回内容中没有识别文本",
            code="upstream_bad_response",
            detail=str(data)[:500],
        ) from exc

    if not content or not content.strip():
        from ..errors import UpstreamError

        raise UpstreamError("识别结果为空，可能是无声或无法识别的音频", code="empty_transcript")

    return content.strip(), data.get("usage") or {}


async def transcribe(
    *, data: bytes, fmt: str, language: str = "auto", model: str | None = None
) -> dict[str, Any]:
    """执行一次识别。返回 transcript, seconds, usage, request_id, is_mock, model。"""
    model = model or settings.asr_model
    fmt = fmt.lower()
    mime = ASR_INPUT_FORMATS.get(fmt, "audio/wav")

    if settings.live_mode:
        audio_b64 = base64.b64encode(data).decode("ascii")
        payload = build_payload(model=model, audio_b64=audio_b64, mime=mime, fmt=fmt, language=language)
        resp = await speech_client.chat_completions(payload)
        transcript, usage = _parse_response(resp)
        seconds = usage.get("seconds")
        request_id = resp.get("id")
        is_mock = False
    else:
        log.info("模拟模式：返回占位识别文本（未调用上游）")
        transcript = (
            "【模拟模式】未配置 SPEECH_API_KEY，这里是占位识别结果。"
            "请在 .env 中填入真实密钥并设 MOCK_MODE=false 后重启服务。"
        )
        usage, seconds, request_id, is_mock = {}, None, None, True

    return {
        "transcript": transcript,
        "seconds": seconds,
        "usage": usage,
        "request_id": request_id,
        "is_mock": is_mock,
        "model": model,
    }
