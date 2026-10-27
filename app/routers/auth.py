"""鉴权路由：注册、登录、当前用户，以及可选的微信扫码登录。

微信登录完全可配置：未设置 WECHAT_APP_ID / WECHAT_APP_SECRET 时，
相关接口返回 404（code=wechat_not_configured），前端自动隐藏入口，账号密码登录不受影响。
"""

from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user, require_wechat_enabled
from ..errors import AppError, AuthError, ConfigError
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse
from ..security import create_access_token, hash_password, validate_password, validate_username, verify_password

log = logging.getLogger("voice_atelier.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

# 微信扫码登录的 state 临时缓存（进程内，生产环境建议换 Redis）
_WX_STATE_TTL = 300
_wx_states: dict[str, float] = {}


def _issue_token(user: User) -> dict:
    token = create_access_token(user.id, user.username)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "user": user.to_dict(),
    }


def _cleanup_states() -> None:
    now = time.time()
    for k, v in list(_wx_states.items()):
        if now - v > _WX_STATE_TTL:
            _wx_states.pop(k, None)


# ------------------------------------------------------------------ 账号密码


@router.post("/register", response_model=TokenResponse, summary="注册")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    try:
        username = validate_username(body.username)
        password = validate_password(body.password)
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_credential") from exc

    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise AppError("该用户名已被注册", code="username_taken", status_code=409)

    if body.email:
        email = body.email.strip().lower()
        if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise AppError("该邮箱已被注册", code="email_taken", status_code=409)
    else:
        email = None

    user = User(
        username=username,
        email=email,
        nickname=(body.nickname or "").strip() or username,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("新用户注册：%s", username)
    return _issue_token(user)


@router.post("/login", response_model=TokenResponse, summary="登录")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    username = (body.username or "").strip()
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None and "@" in username:
        user = db.execute(select(User).where(User.email == username.lower())).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        # 统一提示，避免用户名枚举
        raise AuthError("用户名或密码不正确", code="invalid_credential")
    if not user.is_active:
        raise AuthError("账号已被禁用，请联系管理员", code="account_disabled", status_code=403)

    return _issue_token(user)


@router.get("/me", summary="当前登录用户")
def me(current: User = Depends(get_current_user)):
    return current.to_dict()


@router.post("/logout", summary="退出登录（前端清除令牌即可）")
def logout():
    return {"ok": True, "message": "请在客户端清除 access_token"}


# ------------------------------------------------------------------ 微信扫码登录（可选）


@router.get("/wechat/qr", summary="获取微信扫码登录地址")
def wechat_qr():
    require_wechat_enabled()
    _cleanup_states()
    state = secrets.token_urlsafe(24)
    _wx_states[state] = time.time()

    params = {
        "appid": settings.wechat_app_id,
        "redirect_uri": settings.wechat_redirect_uri,
        "response_type": "code",
        "scope": "snsapi_login",
        "state": state,
    }
    url = "https://open.weixin.qq.com/connect/qrconnect?" + urllib.parse.urlencode(params) + "#wechat_redirect"
    return {"authorize_url": url, "state": state, "expires_in": _WX_STATE_TTL}


@router.get("/wechat/callback", summary="微信授权回调")
async def wechat_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    require_wechat_enabled()

    if not code:
        return RedirectResponse(url="/static/oauth_callback.html?error=wechat_cancelled")
    if not state or state not in _wx_states:
        return RedirectResponse(url="/static/oauth_callback.html?error=wechat_state_invalid")
    _wx_states.pop(state, None)

    # 1) code 换 access_token
    token_url = "https://api.weixin.qq.com/sns/oauth2/access_token"
    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(token_url, params=params)
            tk = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("微信换取 access_token 失败：%s", exc)
        raise ConfigError("微信登录服务暂时不可用，请改用用户名密码登录", code="wechat_unavailable") from exc

    if tk.get("errcode"):
        log.warning("微信返回错误：%s", tk)
        raise ConfigError(
            f"微信登录失败：{tk.get('errmsg', '未知错误')}", code="wechat_error", status_code=400
        )

    openid, unionid, access_token = tk.get("openid"), tk.get("unionid"), tk.get("access_token")

    # 2) 拉取用户昵称（失败不阻断流程）
    nickname = None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.weixin.qq.com/sns/userinfo",
                params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
            )
            info = r.json()
            nickname = info.get("nickname")
    except Exception:  # noqa: BLE001
        pass

    # 3) 已绑定则直接登录，否则自动创建账号
    user = db.execute(select(User).where(User.wechat_openid == openid)).scalar_one_or_none()
    if user is None:
        base = f"wx_{openid[-8:]}"
        username = base
        n = 1
        while db.execute(select(User).where(User.username == username)).scalar_one_or_none():
            n += 1
            username = f"{base}_{n}"
        user = User(
            username=username,
            nickname=nickname or f"微信用户{openid[-4:]}",
            # 微信用户无本地密码，生成不可使用的随机占位哈希
            password_hash=hash_password(secrets.token_urlsafe(32)),
            wechat_openid=openid,
            wechat_unionid=unionid,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        log.info("微信用户首次登录，已创建账号：%s", username)

    token = create_access_token(user.id, user.username)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    return RedirectResponse(url=f"/static/oauth_callback.html?token={urllib.parse.quote(token)}")


@router.get("/wechat/status", summary="微信登录是否可用")
def wechat_status():
    return {
        "enabled": settings.wechat_enabled,
        "reason": None if settings.wechat_enabled else "未配置 WECHAT_APP_ID / WECHAT_APP_SECRET",
    }
