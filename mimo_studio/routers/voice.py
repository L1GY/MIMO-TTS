"""我的音色：上传参考音频即完成克隆音色创建（MiMo 无需预建音色 ID）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import config
from database import get_db
from models import User, Voice
from models.base import now
from routers.deps import redirect, render, require_user, write_log
from schemas import VoiceCreateForm, VoiceRenameForm
from services import audio_service, security

log = logging.getLogger("mimo.voice")
router = APIRouter(tags=["voice"])

CONSENT_TEXT = (
    "本人确认对该声音拥有合法使用权或已取得声音权利人的明确授权，"
    "承诺不将克隆音色用于冒充他人、诈骗、虚假信息等违法违规用途，"
    "并知悉因滥用产生的一切责任由本人承担。"
)


@router.get("/voices")
def voice_list(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    voices = db.scalars(
        select(Voice).where(Voice.user_id == user.id, Voice.kind == "clone").order_by(Voice.created_at.desc())
    ).all()
    return render(
        request, "voices.html", user,
        voices=voices,
        consent_text=CONSENT_TEXT,
        sample_min=config.SAMPLE_MIN_SECONDS,
        sample_max=config.SAMPLE_MAX_SECONDS,
        sample_mb=config.SAMPLE_MAX_MB,
    )


@router.post("/voices")
async def create_voice(
    request: Request,
    name: str = Form(default=""),
    desc: str = Form(default=""),
    consent: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    def fail(message: str):
        return redirect("/voices", err=message)

    # 1) 授权协议必须勾选，且留痕入库
    if consent not in ("1", "on", "true", "yes"):
        return fail("请先勾选声音授权协议")

    # 2) 表单字段
    try:
        form = VoiceCreateForm(name=name, desc=desc, consent=True)
    except ValidationError as exc:
        msg = str(exc.errors()[0].get("msg", "输入不合法")).replace("Value error, ", "")
        return fail(msg)

    # 3) 文件校验（后端二次校验，前端只是体验层）
    if file is None or not file.filename:
        return fail("请选择要上传的音色样本")

    ext = audio_service.ext_of(file.filename)
    if ext not in config.SAMPLE_ALLOWED_EXT:
        return fail("仅支持 wav 或 mp3 格式的音频")

    data = await file.read()
    if not data:
        return fail("上传的文件是空的")
    if len(data) > config.SAMPLE_MAX_MB * 1024 * 1024:
        return fail(f"文件超过 {config.SAMPLE_MAX_MB}MB，请压缩后再上传")

    # 4) 落盘 + 时长校验（3-10 秒）
    rel_path, abs_path = audio_service.save_sample(data, file.filename)
    try:
        duration = audio_service.probe_duration(abs_path)
    except audio_service.AudioError as exc:
        audio_service.delete_static_file(rel_path)
        return fail(str(exc))

    if duration < config.SAMPLE_MIN_SECONDS:
        audio_service.delete_static_file(rel_path)
        return fail(f"样本时长 {duration:.1f}s 太短，建议 3-10 秒清晰人声")
    if duration > config.SAMPLE_MAX_SECONDS:
        audio_service.delete_static_file(rel_path)
        return fail(f"样本时长 {duration:.1f}s 太长，建议 3-10 秒清晰人声")

    # 5) 建音色记录：这一步就完成了「创建」，无需调用远程接口
    voice = Voice(
        user_id=user.id,
        kind="clone",
        name=form.name,
        desc=form.desc,
        sample_path=rel_path,
        sample_mime=audio_service.mime_of(ext),
        sample_size=len(data),
        sample_seconds=round(duration, 2),
        consent=True,
        consent_at=now(),
        consent_text=CONSENT_TEXT,
        status="active",
    )
    db.add(voice)
    db.commit()

    write_log(db, user, "voice.create",
              f"创建音色「{voice.name}」：{duration:.1f}s / {audio_service.human_size(len(data))} / {file.filename}",
              security.client_ip(request))
    log.info("用户 %s 创建音色 %s", user.username, voice.id)
    return redirect("/voices", ok=f"音色「{voice.name}」已创建，可直接用于合成")


@router.post("/voices/{voice_id}/rename")
def rename_voice(
    request: Request,
    voice_id: str,
    name: str = Form(default=""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    voice = db.get(Voice, voice_id)
    if voice is None or voice.user_id != user.id:
        return redirect("/voices", err="音色不存在")

    try:
        form = VoiceRenameForm(name=name)
    except ValidationError:
        return redirect("/voices", err="音色名称需为 1-24 个字符")

    old = voice.name
    voice.name = form.name
    db.commit()

    write_log(db, user, "voice.rename", f"音色 {voice_id}：{old} → {form.name}", security.client_ip(request))
    return redirect("/voices", ok="已重命名")


@router.post("/voices/{voice_id}/delete")
def delete_voice(
    request: Request,
    voice_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    voice = db.get(Voice, voice_id)
    if voice is None or voice.user_id != user.id:
        return redirect("/voices", err="音色不存在")

    audio_service.delete_static_file(voice.sample_path)
    name = voice.name
    db.delete(voice)
    db.commit()

    write_log(db, user, "voice.delete", f"删除音色「{name}」({voice_id})", security.client_ip(request))
    return redirect("/voices", ok=f"音色「{name}」已删除")
