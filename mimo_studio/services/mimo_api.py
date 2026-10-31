"""MiMo 官方语音合成 API 统一封装。

======================================================================
实测校准（2026-10 用真实 Key 验证，务必注意这三点）
======================================================================
1) messages 必须包含 role=assistant，content 为待合成文本。
   传 role=user 会直接 400：
   {"param": "messages must contain an assistant role for TTS model"}
2) 预置音色：audio.voice 传官方音色标识（如 冰糖 / Mia）。
3) 克隆音色：audio.voice 必须传 **DataURL**（data:audio/wav;base64,xxx），
   传裸 base64 会 400：{"param": "audio.voice must be a DataURL for voice clone model"}
   这也是「无需提前创建音色 ID」的原因——每次合成把参考音频带上即可。
======================================================================
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from pathlib import Path

import httpx

from config import config

log = logging.getLogger("mimo.api")

ROLE_ASSISTANT = "assistant"  # 官方硬性要求，不要改成 user


class MimoError(Exception):
    """带有用户可读提示的 API 异常。"""

    def __init__(self, message: str, code: str = "api_error", status: int | None = None,
                 raw: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.raw = raw

    def __str__(self) -> str:
        return self.message


# ---------------------------------------------------------------- 错误映射
def _friendly(status: int, payload: dict | str | None) -> MimoError:
    """把上游错误翻译成用户能看懂的话，同时保留原始信息便于排查。"""
    raw = ""
    param = ""
    message = ""
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        if isinstance(err, dict):
            message = str(err.get("message") or "")
            param = str(err.get("param") or "")
        raw = json.dumps(payload, ensure_ascii=False)[:500]
    elif isinstance(payload, str):
        raw = payload[:500]
        message = payload[:200]

    text = f"{message} {param}".lower()

    if status in (401, 403):
        return MimoError("API Key 无效或没有该模型的访问权限，请到后台检查密钥配置", "auth", status, raw)
    if status == 429:
        return MimoError("请求过于频繁，已触发上游限流，请稍后重试", "rate_limit", status, raw)
    if "balance" in text or "insufficient" in text or "quota" in text or "额度" in text:
        return MimoError("MiMo 账户额度不足，请到官方控制台充值后再试", "insufficient_balance", status, raw)
    if status == 413:
        return MimoError("音频体积超过上游限制，请缩短参考音频后重试", "too_large", status, raw)
    if status >= 500:
        return MimoError(f"上游服务暂时不可用（{status}），请稍后重试", "upstream", status, raw)
    if status == 400:
        detail = param or message or "请求参数不合法"
        return MimoError(f"参数错误：{detail}", "bad_request", status, raw)
    return MimoError(f"调用失败（HTTP {status}）{message[:120]}", "api_error", status, raw)


# ---------------------------------------------------------------- 底层请求
def _post(payload: dict, api_key: str) -> dict:
    url = f"{config.MIMO_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "api-key": api_key,          # 官方认证头就是 api-key
        "Content-Type": "application/json",
    }

    last_error: MimoError | None = None
    for attempt in range(1, config.API_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=config.API_TIMEOUT) as client:
                log.info("调用 MiMo model=%s 第 %s 次", payload.get("model"), attempt)
                resp = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            last_error = MimoError("请求超时，可能是文本过长或网络不稳定，请重试", "timeout")
            log.warning("第 %s 次调用超时", attempt)
        except httpx.HTTPError as exc:
            last_error = MimoError(f"网络异常：{exc}", "network")
            log.warning("第 %s 次调用网络异常：%s", attempt, exc)
        else:
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    raise MimoError("上游返回了非 JSON 内容，请稍后重试", "bad_response", 200,
                                    resp.text[:300]) from None

            try:
                payload_err = resp.json()
            except ValueError:
                payload_err = resp.text

            error = _friendly(resp.status_code, payload_err)
            # 4xx（除 429）重试也没用，直接抛出
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise error
            last_error = error

        if attempt < config.API_MAX_RETRIES:
            time.sleep(min(2 ** attempt, 6))

    raise last_error or MimoError("调用失败，原因未知", "unknown")


def _extract_audio(data: dict) -> bytes:
    """从响应里取 base64 音频并解码。"""
    try:
        message = (data.get("choices") or [{}])[0].get("message") or {}
        audio = message.get("audio") or {}
        b64 = audio.get("data")
    except (AttributeError, IndexError, TypeError):
        b64 = None

    if not b64:
        # 部分情况下上游把音频放在别的字段，尽量给出可读提示
        preview = json.dumps(data, ensure_ascii=False)[:300]
        raise MimoError(f"响应中没有音频数据，可能是模型或参数不对：{preview}", "no_audio")

    try:
        return base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise MimoError(f"音频数据解码失败：{exc}", "decode") from exc


def _speed(speed: float) -> float:
    return max(config.SPEED_MIN, min(config.SPEED_MAX, float(speed or 1.0)))


# ---------------------------------------------------------------- 对外接口
def synthesis_tts(text: str, voice_name: str, speed: float = 1.0, api_key: str | None = None) -> bytes:
    """用 MiMo 预置音色合成，返回音频字节。"""
    key = (api_key or config.MIMO_API_KEY or "").strip()
    if not key:
        raise MimoError("尚未配置 MiMo API Key，请到「管理后台 → 系统配置」填写", "no_key")
    if not text.strip():
        raise MimoError("待合成文本为空", "empty_text")

    payload = {
        "model": config.TTS_MODEL,
        "messages": [{"role": ROLE_ASSISTANT, "content": text}],
        "audio": {
            "format": config.AUDIO_FORMAT,
            "voice": voice_name,          # 预置音色：直接传官方音色标识
            "speed": _speed(speed),
        },
    }
    return _extract_audio(_post(payload, key))


def synthesis_clone_tts(text: str, voice_audio_path: str | Path, speed: float = 1.0,
                        api_key: str | None = None) -> bytes:
    """用本地参考音频做克隆合成，返回音频字节。

    MiMo 无需预先创建音色：每次把参考音频转成 DataURL 放在 audio.voice 里。
    """
    key = (api_key or config.MIMO_API_KEY or "").strip()
    if not key:
        raise MimoError("尚未配置 MiMo API Key，请到「管理后台 → 系统配置」填写", "no_key")
    if not text.strip():
        raise MimoError("待合成文本为空", "empty_text")

    path = Path(voice_audio_path)
    if not path.is_file():
        raise MimoError("参考音频文件不存在，请重新上传音色样本", "sample_missing")

    raw = path.read_bytes()
    if not raw:
        raise MimoError("参考音频文件为空，请重新上传", "sample_empty")
    if len(raw) > config.SAMPLE_MAX_MB * 1024 * 1024:
        raise MimoError("参考音频过大，请上传 10MB 以内的样本", "sample_too_large")

    mime = mimetypes.guess_type(path.name)[0] or "audio/mpeg"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    payload = {
        "model": config.CLONE_MODEL,
        "messages": [{"role": ROLE_ASSISTANT, "content": text}],
        "audio": {
            "format": config.AUDIO_FORMAT,
            "voice": data_url,            # 克隆音色：必须是 DataURL
            "speed": _speed(speed),
        },
    }
    return _extract_audio(_post(payload, key))
