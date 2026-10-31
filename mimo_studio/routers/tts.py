"""语音合成：合成页、提交任务、任务状态轮询、合成记录。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models import Task, User, Voice
from routers.deps import redirect, render, require_user, write_log
from schemas import TtsSubmitForm
from services import audio_service, settings_service, task_service, text_utils, security

log = logging.getLogger("mimo.tts")
router = APIRouter(tags=["tts"])


# ---------------------------------------------------------------- 页面上下文
def _voice_lists(db: Session, user: User):
    presets = db.scalars(
        select(Voice).where(Voice.kind == "preset", Voice.status == "active").order_by(Voice.created_at)
    ).all()
    mine = db.scalars(
        select(Voice).where(
            Voice.user_id == user.id, Voice.kind == "clone", Voice.status == "active"
        ).order_by(Voice.created_at.desc())
    ).all()
    return presets, mine


def _index_context(db: Session, user: User, *, task: Task | None, form: dict | None, err: str | None):
    presets, mine = _voice_lists(db, user)
    return {
        "presets": presets,
        "my_voices": mine,
        "task": task,
        "form": form or {},
        "err_msg": err,
        "max_len": settings_service.get_int(db, "max_text_len", config.MAX_TEXT_LEN),
        "api_ready": settings_service.is_configured(db),
        "quota_left": user.quota_left,
        "announcement": settings_service.get(db, "announcement"),
    }


# ---------------------------------------------------------------- 合成页
@router.get("/")
def index(
    request: Request,
    task: str | None = Query(default=None),
    reuse: str | None = Query(default=None),
    voice: str | None = Query(default=None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    current = None
    if task:
        current = db.get(Task, task)
        # 越权保护：别人的任务不展示
        if current and current.user_id != user.id:
            current = None

    # 「一键复用」：把历史记录的文本、音色、语速回填到表单
    form = None
    if reuse:
        src = db.get(Task, reuse)
        if src and src.user_id == user.id:
            form = {"text": src.text, "voice_id": src.voice_id or "", "speed": src.speed}
    elif voice:
        form = {"voice_id": voice}

    return render(request, "index.html", user,
                  **_index_context(db, user, task=current, form=form, err=None))


@router.post("/tts/submit")
def submit(
    request: Request,
    text: str = Form(default=""),
    voice_id: str = Form(default=""),
    speed: str = Form(default="1.0"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    form = {"text": text, "voice_id": voice_id, "speed": speed}

    def fail(message: str):
        return render(request, "index.html", user,
                      **_index_context(db, user, task=None, form=form, err=message))

    # 1) 参数校验
    try:
        data = TtsSubmitForm(text=text, voice_id=voice_id, speed=float(speed or 1.0))
    except (ValidationError, ValueError) as exc:
        msg = "请检查输入内容"
        if isinstance(exc, ValidationError) and exc.errors():
            msg = str(exc.errors()[0].get("msg", msg)).replace("Value error, ", "")
        return fail(msg)

    # 2) 服务是否就绪
    if not settings_service.is_configured(db):
        return fail("管理员尚未配置 MiMo API Key，暂时无法合成")

    # 3) 文本处理：清洗 → 长度校验 → 敏感词遮蔽
    cleaned = text_utils.normalize(data.text)
    max_len = settings_service.get_int(db, "max_text_len", config.MAX_TEXT_LEN)
    if len(cleaned) > max_len:
        return fail(f"文本超过 {max_len} 字，请精简后再试")

    cleaned, hits = text_utils.filter_sensitive(cleaned, settings_service.sensitive_words(db))
    if hits:
        log.info("用户 %s 文本命中敏感词：%s", user.username, hits)

    # 4) 额度校验（按字符计费）
    cost = len(cleaned)
    if cost > user.quota_left:
        return fail(f"剩余额度不足：本次需要 {cost} 字，当前仅剩 {user.quota_left} 字，请联系管理员调整")

    # 5) 音色归属校验
    voice = db.get(Voice, data.voice_id)
    if voice is None or voice.status != "active":
        return fail("所选音色不存在或已下架")
    if voice.kind == "clone" and voice.user_id != user.id:
        return fail("无权使用该音色")

    # 6) 建任务 + 扣额度（失败会在后台线程里退回）
    task = Task(
        user_id=user.id,
        voice_id=voice.id,
        voice_name=voice.name,
        voice_kind=voice.kind,
        text=cleaned,
        text_len=cost,
        speed=data.speed,
        status="queued",
        progress=0,
    )
    db.add(task)
    user.used_chars = int(user.used_chars) + cost
    voice.use_count = int(voice.use_count or 0) + 1
    db.commit()
    db.refresh(task)

    write_log(db, user, "tts.submit",
              f"提交任务 {task.id}：{cost} 字，音色「{voice.name}」，语速 {data.speed}"
              + (f"，敏感词 {','.join(hits)}" if hits else ""),
              security.client_ip(request))

    task_service.submit(task.id)
    return redirect(f"/?task={task.id}", ok="已提交，正在后台生成")


# ---------------------------------------------------------------- 状态轮询
@router.get("/api/tasks/{task_id}")
def task_status(task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if task.user_id != user.id and not user.is_admin:
        return JSONResponse({"error": "无权访问"}, status_code=403)

    return {
        "id": task.id,
        "status": task.status,
        "status_text": task.status_text,
        "progress": task.progress,
        "error": task.error,
        "audio_url": task.audio_url,
        "duration_text": task.duration_text,
        "size_text": task.size_text,
        "download_url": f"/records/{task.id}/download" if task.audio_url else None,
        "reuse_url": f"/?reuse={task.id}",
    }


# ---------------------------------------------------------------- 记录
@router.get("/records")
def records(
    request: Request,
    page: int = Query(default=1, ge=1),
    status: str = Query(default="all"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    page_size = 10
    stmt = select(Task).where(Task.user_id == user.id)
    count_stmt = select(func.count()).select_from(Task).where(Task.user_id == user.id)
    if status in ("queued", "running", "success", "failed"):
        stmt = stmt.where(Task.status == status)
        count_stmt = count_stmt.where(Task.status == status)

    total = db.scalar(count_stmt) or 0
    items = db.scalars(
        stmt.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return render(
        request, "records.html", user,
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
        status=status,
    )


@router.post("/records/{task_id}/delete")
def delete_record(
    request: Request,
    task_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        return redirect("/records", err="记录不存在")

    audio_service.delete_static_file(task.result_path)
    db.delete(task)
    db.commit()

    write_log(db, user, "tts.delete", f"删除合成记录 {task_id}", security.client_ip(request))
    return redirect("/records", ok="已删除该记录")


@router.get("/records/{task_id}/download")
def download(task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None or task.result_path is None:
        return redirect("/records", err="音频不存在")
    if task.user_id != user.id and not user.is_admin:
        return redirect("/records", err="无权下载该音频")

    path = config.STATIC_DIR / task.result_path
    if not path.is_file():
        return redirect("/records", err="音频文件已丢失")

    filename = f"mimo_tts_{task.created_at.strftime('%Y%m%d_%H%M')}.mp3"
    return FileResponse(path, media_type="audio/mpeg", filename=filename)
