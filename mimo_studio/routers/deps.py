"""路由公共依赖：模板渲染、登录校验、权限校验、日志记录。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models import OpLog, User
from services import security

# ---------------------------------------------------------------- 模板
templates = Jinja2Templates(directory=str(config.BASE_DIR / "templates"))


def _fmt_time(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not value:
        return "—"
    return value.strftime(fmt)


def _fmt_short(value: datetime | None) -> str:
    if not value:
        return "—"
    now = datetime.now()
    if value.date() == now.date():
        return value.strftime("今天 %H:%M")
    return value.strftime("%m-%d %H:%M")


templates.env.filters["dt"] = _fmt_time
templates.env.filters["short"] = _fmt_short
templates.env.globals["APP_NAME"] = config.APP_NAME
templates.env.globals["APP_SUBTITLE"] = config.APP_SUBTITLE


def render(request: Request, name: str, user: User | None = None, **context):
    """统一的模板渲染入口，自动补齐全局变量。"""
    ctx = {
        "request": request,
        "user": user,
        "current_path": request.url.path,
        "ok_msg": request.query_params.get("ok"),
        "err_msg": request.query_params.get("err"),
        "site": {
            "name": config.APP_NAME,
            "subtitle": config.APP_SUBTITLE,
            "speed_min": config.SPEED_MIN,
            "speed_max": config.SPEED_MAX,
            "max_text_len": config.MAX_TEXT_LEN,
            "sample_min": config.SAMPLE_MIN_SECONDS,
            "sample_max": config.SAMPLE_MAX_SECONDS,
            "sample_mb": config.SAMPLE_MAX_MB,
        },
    }
    ctx.update(context)
    return templates.TemplateResponse(request, name, ctx)


def redirect(path: str, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    """PRG 模式跳转；提示信息通过查询参数传递，不依赖服务端会话存储。"""
    params = []
    if ok:
        params.append(f"ok={quote(ok)}")
    if err:
        params.append(f"err={quote(err)}")
    if not params:
        return RedirectResponse(path, status_code=303)
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + sep + "&".join(params), status_code=303)


# ---------------------------------------------------------------- 登录态
class AuthRequired(Exception):
    """未登录访问受保护页面，交给全局异常处理器跳转登录页。"""

    def __init__(self, path: str):
        self.path = path


class Forbidden(Exception):
    """已登录但没有权限。"""


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = security.read_session_token(request.cookies.get(config.SESSION_COOKIE))
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        return None
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise AuthRequired(str(request.url.path))
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise Forbidden()
    return user


# ---------------------------------------------------------------- 日志
def write_log(db: Session, user: User | None, action: str, detail: str, ip: str = "") -> None:
    """写操作日志。失败不影响主流程。"""
    try:
        db.add(OpLog(
            user_id=user.id if user else None,
            username=user.username if user else "",
            action=action,
            detail=detail[:800],
            ip=ip[:64],
        ))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
