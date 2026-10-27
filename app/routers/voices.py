"""自定义音色（音色设计成果）的增删改查。全部要求登录。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError
from ..models import TTSRecord, User, VoicePreset

log = logging.getLogger("voice_atelier.voices")
router = APIRouter(prefix="/api/voices", tags=["voices"])

# 卡片标识色，按顺序分配给新建音色
PALETTE = ["#3B2FD6", "#00A6C4", "#7448E8", "#0E8A5F", "#D97706", "#C62F26"]


class VoiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    sample_text: str | None = Field(default=None, max_length=2000)


class VoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, min_length=1, max_length=1000)


@router.get("", summary="我的音色列表")
def list_voices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = select(VoicePreset).where(VoicePreset.user_id == current.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(VoicePreset.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return {"items": [v.to_dict() for v in rows], "total": total, "page": page, "page_size": page_size}


@router.post("", summary="保存一个音色设计")
def create_voice(body: VoiceCreate, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = body.name.strip()
    desc = body.description.strip()
    if not name or not desc:
        raise AppError("音色名称与描述都不能为空", code="invalid_voice")

    dup = db.execute(
        select(VoicePreset).where(VoicePreset.user_id == current.id, VoicePreset.name == name)
    ).scalar_one_or_none()
    if dup:
        raise AppError("已经有一个同名音色了，换个名字吧", code="voice_name_taken", status_code=409)

    count = db.scalar(
        select(func.count()).select_from(
            select(VoicePreset).where(VoicePreset.user_id == current.id).subquery()
        )
    ) or 0

    preset = VoicePreset(
        user_id=current.id,
        name=name,
        description=desc,
        sample_text=(body.sample_text or "").strip() or None,
        color=PALETTE[count % len(PALETTE)],
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset.to_dict()


@router.patch("/{voice_id}", summary="重命名或修改描述")
def update_voice(
    voice_id: str,
    body: VoiceUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    preset = db.get(VoicePreset, voice_id)
    if preset is None or preset.user_id != current.id:
        raise HTTPException(status_code=404, detail="音色不存在")
    if body.name is not None:
        preset.name = body.name.strip() or preset.name
    if body.description is not None:
        preset.description = body.description.strip() or preset.description
    db.commit()
    db.refresh(preset)
    return preset.to_dict()


@router.delete("/{voice_id}", summary="删除一个自定义音色")
def delete_voice(voice_id: str, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preset = db.get(VoicePreset, voice_id)
    if preset is None or preset.user_id != current.id:
        raise HTTPException(status_code=404, detail="音色不存在")
    # 历史记录保留，但断开关联，避免外键悬挂
    for r in db.execute(
        select(TTSRecord).where(TTSRecord.voice_preset_id == preset.id)
    ).scalars().all():
        r.voice_preset_id = None
    db.delete(preset)
    db.commit()
    return {"ok": True, "id": voice_id}


@router.post("/{voice_id}/use", summary="标记一次使用（统计用）")
def mark_used(voice_id: str, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    preset = db.get(VoicePreset, voice_id)
    if preset is None or preset.user_id != current.id:
        raise HTTPException(status_code=404, detail="音色不存在")
    preset.use_count = (preset.use_count or 0) + 1
    preset.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"ok": True, "use_count": preset.use_count}
