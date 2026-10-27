"""FastAPI 依赖：从请求中解析当前登录用户。

未登录访问受保护接口 → 401 {"error":{"code":"unauthorized",...}}
"""

from __future__ import annotations

import jwt
from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AuthError
from .models import User
from .security import decode_access_token

# auto_error=False：由我们自行抛出统一的中文错误，而不是 FastAPI 默认的 "Not authenticated"
bearer_scheme = HTTPBearer(auto_error=False)


def _load_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("登录状态已失效，请重新登录", code="unauthorized")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None, description="可选：URL 参数形式的令牌，便于直接下载音频"),
    db: Session = Depends(get_db),
) -> User:
    raw = credentials.credentials if credentials else token
    if not raw:
        raise AuthError("请先登录后再使用该功能", code="unauthorized")
    try:
        payload = decode_access_token(raw)
    except jwt.ExpiredSignatureError:
        raise AuthError("登录已过期，请重新登录", code="token_expired") from None
    except jwt.PyJWTError:
        raise AuthError("无效的登录凭证，请重新登录", code="invalid_token") from None

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("无效的登录凭证，请重新登录", code="invalid_token")
    return _load_user(db, user_id)


def require_wechat_enabled() -> None:
    """微信登录开关：未配置时返回 404，明确告知前端隐藏入口。"""
    from .config import settings

    if not settings.wechat_enabled:
        from .errors import AppError

        raise AppError(
            "未配置微信登录（WECHAT_APP_ID / WECHAT_APP_SECRET 为空），请使用用户名密码登录",
            code="wechat_not_configured",
            status_code=404,
        )
