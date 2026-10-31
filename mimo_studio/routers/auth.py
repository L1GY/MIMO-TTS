"""登录 / 注册 / 退出。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models import User
from models.base import now
from routers.deps import get_current_user, redirect, render, write_log
from schemas import LoginForm, RegisterForm
from services import security, settings_service

log = logging.getLogger("mimo.auth")
router = APIRouter(tags=["auth"])


def _safe_next(value: str | None) -> str:
    """只允许站内相对路径，防止开放重定向。"""
    if not value:
        return "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _set_session(resp, user: User):
    token = security.create_session_token(user.id)
    resp.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )
    return resp


@router.get("/login")
def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return redirect("/")
    return render(request, "login.html", None, next_path=_safe_next(next))


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    next_path: str = Form(default="/"),
    db: Session = Depends(get_db),
):
    target = _safe_next(next_path)
    try:
        form = LoginForm(username=username.strip(), password=password)
    except ValidationError:
        return render(request, "login.html", None, next_path=target, err_msg="请输入用户名和密码")

    user = db.scalar(select(User).where(func.lower(User.username) == form.username.lower()))
    if user is None or not security.verify_password(form.password, user.password_hash):
        return render(request, "login.html", None, next_path=target, err_msg="用户名或密码不正确")
    if not user.is_active:
        return render(request, "login.html", None, next_path=target, err_msg="该账号已被禁用，请联系管理员")

    user.touch_login()
    db.commit()

    write_log(db, user, "auth.login", f"{user.username} 登录成功", security.client_ip(request))

    resp = _set_session(redirect("/"), user)
    return resp


@router.get("/register")
def register_page(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return redirect("/")
    return render(request, "register.html", None)


@router.post("/register")
def register_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    password2: str = Form(default=""),
    email: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        form = RegisterForm(username=username, password=password, password2=password2, email=email)
        if not form.check_password2():
            raise ValueError("两次输入的密码不一致")
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "输入不合法").replace("Value error, ", "")
        return render(request, "register.html", None, err_msg=msg, form={"username": username, "email": email})
    except ValueError as exc:
        return render(request, "register.html", None, err_msg=str(exc), form={"username": username, "email": email})

    exists = db.scalar(select(User).where(func.lower(User.username) == form.username.lower()))
    if exists:
        return render(request, "register.html", None, err_msg="该用户名已被占用",
                      form={"username": form.username, "email": form.email or ""})

    quota = settings_service.get_int(db, "default_quota", config.DEFAULT_QUOTA_CHARS)
    user = User(
        username=form.username,
        email=form.email,
        password_hash=security.hash_password(form.password),
        role="user",
        is_active=True,
        quota_chars=quota,
        used_chars=0,
        last_login_at=now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    write_log(db, user, "auth.register", f"{user.username} 注册成功，赠送 {quota} 字额度",
              security.client_ip(request))
    log.info("新用户注册：%s", user.username)

    resp = _set_session(redirect("/", ok="注册成功，已为你自动登录"), user)
    return resp


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        write_log(db, user, "auth.logout", f"{user.username} 退出登录", security.client_ip(request))
    resp = redirect("/login", ok="已退出登录")
    resp.delete_cookie(config.SESSION_COOKIE, path="/")
    return resp
