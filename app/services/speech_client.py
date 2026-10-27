"""上游语音服务平台 HTTP 客户端。

TTS 与 ASR 共用同一个 OpenAI 兼容端点：
    POST {SPEECH_API_BASE_URL}/chat/completions
鉴权头（二选一）：
    api-key: $SPEECH_API_KEY     或     Authorization: Bearer $SPEECH_API_KEY

本模块负责：超时控制、限流/抖动重试、上游错误码 → 业务异常映射。
密钥只从 settings 读取，任何响应中都不会回传。
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from ..config import settings
from ..errors import AuthError, ConfigError, RateLimitError, UpstreamError

log = logging.getLogger("voice_atelier.upstream")

# 可重试的状态码：限流与服务端错误
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


def _extract_upstream_message(body: Any) -> str:
    """从上游错误响应中尽量抽取可读信息。"""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or "")
        if isinstance(err, str):
            return err
        if body.get("message"):
            return str(body["message"])
    if isinstance(body, str):
        return body[:300]
    return ""


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body: Any = resp.json()
    except Exception:  # noqa: BLE001
        body = resp.text[:500]

    msg = _extract_upstream_message(body) or f"上游返回 HTTP {resp.status_code}"

    if resp.status_code in (401, 403):
        raise AuthError(
            "上游密钥无效、已过期或无权限，请检查 .env 中的 SPEECH_API_KEY",
            code="upstream_auth_failed",
            detail=msg,
        )
    if resp.status_code == 429:
        raise RateLimitError(
            "上游平台限流（RPM/TPM 超限），请稍后重试",
            code="upstream_rate_limited",
            detail=msg,
        )
    if resp.status_code == 413:
        raise UpstreamError(
            "音频体积过大，上游要求 base64 编码后不超过 10MB",
            code="upstream_payload_too_large",
            status_code=413,
            detail=msg,
        )
    if 400 <= resp.status_code < 500:
        raise UpstreamError(
            f"请求被上游服务拒绝：{msg}",
            code="upstream_bad_request",
            status_code=400,
            detail=msg,
        )
    raise UpstreamError(
        f"上游服务异常（HTTP {resp.status_code}），请稍后重试",
        code="upstream_error",
        status_code=502,
        detail=msg,
    )


async def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
    """调用 /chat/completions，返回解析后的 JSON dict。

    抛出：
        ConfigError    —— 未配置密钥或必需的上游参数
        AuthError      —— 密钥无效
        RateLimitError —— 被限流
        UpstreamError  —— 其它上游错误
    """
    if not settings.speech_api_key:
        raise ConfigError(
            "未配置 SPEECH_API_KEY，无法调用上游语音服务。"
            "请在 .env 中填写密钥，或设置 MOCK_MODE=true 使用模拟模式",
            code="missing_api_key",
        )

    ready, missing = settings.upstream_ready()
    if not ready:
        raise ConfigError(
            "上游配置不完整，缺：" + "、".join(missing) + "。请参考 .env.example 补齐后重启",
            code="upstream_not_configured",
        )

    headers = {
        "api-key": settings.speech_api_key,
        "Authorization": f"Bearer {settings.speech_api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    attempts = max(1, settings.speech_max_retries + 1)

    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.speech_timeout, connect=15.0)) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(settings.chat_completions_url, json=payload, headers=headers)

                if resp.status_code in RETRYABLE_STATUS and attempt < attempts:
                    delay = (0.8 * (2 ** (attempt - 1))) + random.uniform(0, 0.4)
                    log.warning(
                        "上游返回 %s，第 %s/%s 次重试，%.1fs 后重试",
                        resp.status_code, attempt, attempts, delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = None
                    continue

                _raise_for_status(resp)

                try:
                    return resp.json()
                except Exception as exc:  # noqa: BLE001
                    raise UpstreamError(
                        "无法解析上游返回的响应",
                        code="upstream_bad_response",
                        detail=resp.text[:300],
                    ) from exc

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < attempts:
                    await asyncio.sleep(0.8 * (2 ** (attempt - 1)))
                    log.warning("上游请求超时，第 %s/%s 次重试", attempt, attempts)
                    continue
                raise UpstreamError(
                    f"调用上游超时（超过 {settings.speech_timeout:.0f} 秒），请稍后重试或缩短文本",
                    code="upstream_timeout",
                    status_code=504,
                ) from exc

            except httpx.ConnectError as exc:
                last_exc = exc
                if attempt < attempts:
                    await asyncio.sleep(0.8 * (2 ** (attempt - 1)))
                    continue
                raise UpstreamError(
                    "无法连接上游服务，请检查网络或 SPEECH_API_BASE_URL 配置",
                    code="upstream_unreachable",
                    status_code=503,
                ) from exc

            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < attempts:
                    await asyncio.sleep(0.8 * (2 ** (attempt - 1)))
                    continue
                raise UpstreamError(
                    "调用上游服务时发生网络错误",
                    code="upstream_network_error",
                    status_code=502,
                    detail=str(exc),
                ) from exc

    # 理论上不可达，保险起见
    raise UpstreamError("调用上游服务失败，请稍后重试", detail=str(last_exc) if last_exc else None)
