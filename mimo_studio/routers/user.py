"""个人中心：查看资料、额度，修改密码。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_db
from models import Task, User, Voice
from routers.deps import redirect, render, require_user, write_log
from schemas import ChangePasswordForm
from services import security

log = logging.getLogger("mimo.user")
router = APIRouter(tags=["user"])


@router.get("/profile")
def profile(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    voice_count = db.scalar(
        select(func.count()).select_from(Voice).where(Voice.user_id == user.id, Voice.kind == "clone")
    ) or 0
    task_total = db.scalar(select(func.count()).select_from(Task).where(Task.user_id == user.id)) or 0
    task_ok = db.scalar(
        select(func.count()).select_from(Task).where(Task.user_id == user.id, Task.status == "success")
    ) or 0

    return render(
        request, "profile.html", user,
        voice_count=voice_count,
        task_total=task_total,
        task_ok=task_ok,
    )


@router.post("/profile/password")
def change_password(
    request: Request,
    old_password: str = Form(default=""),
    new_password: str = Form(default=""),
    new_password2: str = Form(default=""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    try:
        form = ChangePasswordForm(
            old_password=old_password, new_password=new_password, new_password2=new_password2
        )
    except ValidationError:
        return redirect("/profile", err="新密码至少 6 位")

    if not security.verify_password(form.old_password, user.password_hash):
        return redirect("/profile", err="当前密码不正确")
    if form.new_password != form.new_password2:
        return redirect("/profile", err="两次输入的新密码不一致")
    if form.new_password == form.old_password:
        return redirect("/profile", err="新密码不能与当前密码相同")

    user.password_hash = security.hash_password(form.new_password)
    db.commit()

    write_log(db, user, "user.password", "修改登录密码", security.client_ip(request))
    log.info("用户 %s 修改密码", user.username)
    return redirect("/profile", ok="密码已更新，请牢记新密码")
