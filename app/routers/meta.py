"""应用元信息与健康检查。不返回任何密钥或敏感配置。"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import APP_NAME, APP_NAME_EN, settings

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta", summary="前端初始化所需的能力与开关")
def meta():
    ready, _missing = settings.upstream_ready()
    return {
        "app": APP_NAME,
        "app_en": APP_NAME_EN,
        "version": "1.0.0",
        # live=false 表示运行在模拟模式下（未配置密钥或 MOCK_MODE=true）
        "live_mode": settings.live_mode,
        "mock_mode": not settings.live_mode,
        "upstream_ready": ready,
        "wechat_enabled": settings.wechat_enabled,
        "limits": {
            "max_text_length": settings.max_text_length,
            "max_upload_mb": settings.max_upload_mb,
        },
    }


@router.get("/health", summary="健康检查")
def health():
    return {"status": "ok", "live_mode": settings.live_mode}
