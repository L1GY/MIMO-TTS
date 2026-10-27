"""统一历史记录：合并查看 TTS 与 ASR 调用，并给出用量概览。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ASRRecord, TTSRecord, User
from ..services import storage

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", summary="合并的调用历史")
def list_history(
    type: str = Query(default="all", pattern="^(all|tts|asr)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default="", max_length=128),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items: list[dict] = []
    total = 0

    if type in ("all", "tts"):
        q = select(TTSRecord).where(TTSRecord.user_id == current.id)
        if keyword:
            q = q.where(TTSRecord.text_input.ilike(f"%{keyword}%"))
        total += db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = db.execute(q.order_by(TTSRecord.created_at.desc()).limit(500)).scalars().all()
        items.extend(r.to_dict() for r in rows)

    if type in ("all", "asr"):
        q = select(ASRRecord).where(ASRRecord.user_id == current.id)
        if keyword:
            q = q.where(ASRRecord.transcript.ilike(f"%{keyword}%"))
        total += db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = db.execute(q.order_by(ASRRecord.created_at.desc()).limit(500)).scalars().all()
        items.extend(r.to_dict() for r in rows)

    items.sort(key=lambda x: x["created_at"], reverse=True)
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats", summary="调用量统计")
def stats(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    tts_total = db.scalar(
        select(func.count()).select_from(
            select(TTSRecord).where(TTSRecord.user_id == current.id).subquery()
        )
    ) or 0
    asr_total = db.scalar(
        select(func.count()).select_from(
            select(ASRRecord).where(ASRRecord.user_id == current.id).subquery()
        )
    ) or 0
    tts_recent = db.scalar(
        select(func.count()).select_from(
            select(TTSRecord)
            .where(TTSRecord.user_id == current.id, TTSRecord.created_at >= since)
            .subquery()
        )
    ) or 0
    asr_recent = db.scalar(
        select(func.count()).select_from(
            select(ASRRecord)
            .where(ASRRecord.user_id == current.id, ASRRecord.created_at >= since)
            .subquery()
        )
    ) or 0
    failed = db.scalar(
        select(func.count()).select_from(
            select(TTSRecord)
            .where(TTSRecord.user_id == current.id, TTSRecord.status == "failed")
            .subquery()
        )
    ) or 0
    failed += db.scalar(
        select(func.count()).select_from(
            select(ASRRecord)
            .where(ASRRecord.user_id == current.id, ASRRecord.status == "failed")
            .subquery()
        )
    ) or 0
    chars = db.scalar(
        select(func.coalesce(func.sum(func.length(TTSRecord.text_input)), 0)).where(
            TTSRecord.user_id == current.id
        )
    ) or 0
    audio_bytes = db.scalar(
        select(func.coalesce(func.sum(TTSRecord.audio_size), 0)).where(TTSRecord.user_id == current.id)
    ) or 0

    return {
        "tts_total": tts_total,
        "asr_total": asr_total,
        "tts_last_30d": tts_recent,
        "asr_last_30d": asr_recent,
        "failed_total": failed,
        "tts_chars": chars,
        "audio_bytes": audio_bytes,
    }


@router.delete("/{kind}/{record_id}", summary="按类型删除记录")
def delete_one(
    kind: str,
    record_id: str,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    model = {"tts": TTSRecord, "asr": ASRRecord}.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="未知的记录类型")
    record = db.get(model, record_id)
    if record is None or record.user_id != current.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    storage.delete_file(getattr(record, "audio_path", None) or getattr(record, "stored_path", None))
    db.delete(record)
    db.commit()
    return {"ok": True, "id": record_id}


@router.delete("", summary="清空当前用户的全部历史与音频")
def clear(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for record in db.execute(select(TTSRecord).where(TTSRecord.user_id == current.id)).scalars().all():
        storage.delete_file(record.audio_path)
        db.delete(record)
    for record in db.execute(select(ASRRecord).where(ASRRecord.user_id == current.id)).scalars().all():
        storage.delete_file(record.stored_path)
        db.delete(record)
    db.commit()
    return {"ok": True, "message": "历史记录已清空"}
