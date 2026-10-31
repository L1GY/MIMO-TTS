"""管理员后台：用户、任务、音色、系统配置、操作日志。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models import OpLog, Task, User, Voice
from routers.deps import redirect, render, require_admin, write_log
from services import audio_service, security, settings_service

log = logging.getLogger("mimo.admin")
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------- 概览
@router.get("")
def dashboard(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    week = datetime.now() - timedelta(days=7)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    active_users = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
    total_tasks = db.scalar(select(func.count()).select_from(Task)) or 0
    today_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.created_at >= today)) or 0
    week_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.created_at >= week)) or 0
    ok_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.status == "success")) or 0
    fail_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.status == "failed")) or 0
    running = db.scalar(
        select(func.count()).select_from(Task).where(Task.status.in_(["queued", "running"]))
    ) or 0
    clone_voices = db.scalar(
        select(func.count()).select_from(Voice).where(Voice.kind == "clone")
    ) or 0
    chars = db.scalar(select(func.coalesce(func.sum(Task.text_len), 0))) or 0

    recent = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(8)).all()

    # 近 7 天每日任务量，用于简单柱状图
    daily = []
    for offset in range(6, -1, -1):
        day_start = (datetime.now() - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.created_at >= day_start, Task.created_at < day_end
            )
        ) or 0
        daily.append({"label": day_start.strftime("%m-%d"), "count": count})
    max_daily = max([d["count"] for d in daily] + [1])

    return render(
        request, "admin/dashboard.html", user,
        stats={
            "total_users": total_users,
            "active_users": active_users,
            "total_tasks": total_tasks,
            "today_tasks": today_tasks,
            "week_tasks": week_tasks,
            "ok_tasks": ok_tasks,
            "fail_tasks": fail_tasks,
            "running": running,
            "clone_voices": clone_voices,
            "chars": chars,
            "success_rate": round(ok_tasks / total_tasks * 100, 1) if total_tasks else 0,
        },
        recent=recent,
        daily=daily,
        max_daily=max_daily,
        api_ready=settings_service.is_configured(db),
    )


# ---------------------------------------------------------------- 用户
@router.get("/users")
def users(
    request: Request,
    q: str = Query(default=""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(User.username.like(like))
    items = db.scalars(stmt.limit(200)).all()

    # 每个用户的合成次数
    counts = dict(
        db.execute(
            select(Task.user_id, func.count()).group_by(Task.user_id)
        ).all()
    )
    return render(request, "admin/users.html", user, items=items, counts=counts, q=q)


@router.post("/users/{user_id}/toggle")
def toggle_user(
    request: Request,
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect("/admin/users", err="用户不存在")
    if target.id == admin.id:
        return redirect("/admin/users", err="不能禁用自己")
    if target.is_admin:
        return redirect("/admin/users", err="不能禁用管理员账号")

    target.is_active = not target.is_active
    db.commit()
    state = "启用" if target.is_active else "禁用"
    write_log(db, admin, "admin.user.toggle", f"{state}用户 {target.username}", security.client_ip(request))
    return redirect("/admin/users", ok=f"已{state}用户「{target.username}」")


@router.post("/users/{user_id}/quota")
def update_quota(
    request: Request,
    user_id: str,
    quota_chars: int = Form(default=0),
    reset_used: str = Form(default=""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        return redirect("/admin/users", err="用户不存在")

    if quota_chars < 0:
        return redirect("/admin/users", err="额度不能为负数")
    target.quota_chars = int(quota_chars)
    if reset_used in ("1", "on", "true"):
        target.used_chars = 0
    db.commit()

    write_log(db, admin, "admin.user.quota",
              f"调整 {target.username} 额度为 {quota_chars}"
              + ("（并重置已用）" if reset_used else ""), security.client_ip(request))
    return redirect("/admin/users", ok=f"已更新「{target.username}」的额度")


# ---------------------------------------------------------------- 任务
@router.get("/tasks")
def tasks(
    request: Request,
    status: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page_size = 15
    stmt = select(Task)
    count_stmt = select(func.count()).select_from(Task)
    if status in ("queued", "running", "success", "failed"):
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)

    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    usernames = {u.id: u.username for u in db.scalars(select(User)).all()}

    return render(
        request, "admin/tasks.html", admin,
        items=items, total=total, page=page, status=status,
        pages=max(1, (total + page_size - 1) // page_size),
        usernames=usernames,
    )


# ---------------------------------------------------------------- 音色
@router.get("/voices")
def voices(
    request: Request,
    page: int = Query(default=1, ge=1),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page_size = 15
    total = db.scalar(select(func.count()).select_from(Voice).where(Voice.kind == "clone")) or 0
    items = db.scalars(
        select(Voice).where(Voice.kind == "clone").order_by(Voice.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    usernames = {u.id: u.username for u in db.scalars(select(User)).all()}

    return render(
        request, "admin/voices.html", admin,
        items=items, total=total, page=page,
        pages=max(1, (total + page_size - 1) // page_size),
        usernames=usernames,
    )


@router.post("/voices/{voice_id}/delete")
def delete_voice(
    request: Request,
    voice_id: str,
    reason: str = Form(default="违规音色，管理员删除"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    voice = db.get(Voice, voice_id)
    if voice is None:
        return redirect("/admin/voices", err="音色不存在")

    audio_service.delete_static_file(voice.sample_path)
    name, owner = voice.name, voice.user_id
    db.delete(voice)
    db.commit()

    write_log(db, admin, "admin.voice.delete",
              f"强制删除音色「{name}」({voice_id})，属主 {owner}，原因：{reason}",
              security.client_ip(request))
    return redirect("/admin/voices", ok=f"已删除音色「{name}」")


# ---------------------------------------------------------------- 系统配置
@router.get("/settings")
def settings_page(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return render(
        request, "admin/settings.html", admin,
        api_key_masked=settings_service.masked_api_key(db),
        api_ready=settings_service.is_configured(db),
        default_quota=settings_service.get_int(db, "default_quota", config.DEFAULT_QUOTA_CHARS),
        max_text_len=settings_service.get_int(db, "max_text_len", config.MAX_TEXT_LEN),
        sensitive_words=settings_service.get(db, "sensitive_words"),
        announcement=settings_service.get(db, "announcement"),
        models={"tts": config.TTS_MODEL, "clone": config.CLONE_MODEL, "base": config.MIMO_API_BASE},
    )


@router.post("/settings")
def save_settings(
    request: Request,
    api_key: str = Form(default=""),
    default_quota: int = Form(default=20000),
    max_text_len: int = Form(default=3000),
    sensitive_words: str = Form(default=""),
    announcement: str = Form(default=""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if api_key.strip():
        settings_service.set_value(db, "api_key", api_key.strip())
    if default_quota < 0:
        return redirect("/admin/settings", err="默认额度不能为负数")
    if max_text_len < 50:
        return redirect("/admin/settings", err="单条文本上限至少 50 字")

    settings_service.set_value(db, "default_quota", str(default_quota))
    settings_service.set_value(db, "max_text_len", str(max_text_len))
    settings_service.set_value(db, "sensitive_words", sensitive_words)
    settings_service.set_value(db, "announcement", announcement)

    write_log(db, admin, "admin.settings", "更新系统配置", security.client_ip(request))
    return redirect("/admin/settings", ok="配置已保存")


# ---------------------------------------------------------------- 日志
@router.get("/logs")
def logs(
    request: Request,
    page: int = Query(default=1, ge=1),
    action: str = Query(default=""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    page_size = 20
    stmt = select(OpLog)
    count_stmt = select(func.count()).select_from(OpLog)
    if action.strip():
        stmt = stmt.where(OpLog.action.like(f"%{action.strip()}%"))
        count_stmt = count_stmt.where(OpLog.action.like(f"%{action.strip()}%"))

    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(OpLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return render(
        request, "admin/logs.html", admin,
        items=items, total=total, page=page, action=action,
        pages=max(1, (total + page_size - 1) // page_size),
    )
