"""TTS 路由：合成、历史、音频下载与删除。全部要求登录。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import TTS_FORMATS, preset_voices, settings, voice_display_name
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError
from ..models import TTSRecord, User, VoicePreset
from ..schemas import TTSSynthesizeRequest
from ..services import storage, tts_service

log = logging.getLogger("voice_atelier.tts_api")
router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.get("/options", summary="可用音色、输出格式与模型")
def options(_: User = Depends(get_current_user)):
    # 模型 ID 由服务端下发，前端不写死任何上游协议值
    return {
        "voices": preset_voices(),
        "formats": TTS_FORMATS,
        "models": {
            "preset": settings.tts_model,
            "design": settings.tts_model_design,
            "clone": settings.tts_model_clone,
        },
        "default_model": settings.tts_model,
        "default_voice": settings.tts_default_voice,
        "max_text_length": settings.max_text_length,
    }


def _resolve_voice(
    *, db: Session, user_id: str, model: str, voice: str | None,
    voice_desc: str | None, voice_preset_id: str | None
) -> tuple[str, str | None, str | None, str | None]:
    """把请求里的音色信息解析为 (model, voice_id, voice_desc, voice_name)。"""
    preset = None
    if voice_preset_id:
        preset = db.get(VoicePreset, voice_preset_id)
        if preset is None or preset.user_id != user_id:
            raise AppError("所选音色不存在或不属于当前用户", code="voice_not_found", status_code=404)
        # 自定义音色走音色设计模型，描述作为提示词
        return settings.tts_model_design, None, preset.description, preset.name

    if voice_desc:
        name = (voice_desc.strip()[:16] + "…") if len(voice_desc.strip()) > 16 else voice_desc.strip()
        return (model or settings.tts_model_design), None, voice_desc, name

    if voice:
        return settings.tts_model, voice, None, voice_display_name(voice)

    return settings.tts_model, settings.tts_default_voice, None, voice_display_name(settings.tts_default_voice)


@router.post("/synthesize", summary="文本转语音")
async def synthesize(
    body: TTSSynthesizeRequest,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(body.text) > settings.max_text_length:
        raise AppError(
            f"文本过长，单次合成不超过 {settings.max_text_length} 字",
            code="text_too_long",
        )

    started = time.perf_counter()
    model, voice_id, voice_desc, voice_name = _resolve_voice(
        db=db,
        user_id=current.id,
        model=body.model,
        voice=body.voice,
        voice_desc=body.voice_desc,
        voice_preset_id=body.voice_preset_id,
    )

    record = TTSRecord(
        user_id=current.id,
        model=model,
        voice=voice_id,
        voice_name=voice_name,
        voice_desc=voice_desc,
        voice_preset_id=body.voice_preset_id,
        audio_format=body.audio_format,
        optimize_text=body.optimize_text,
        text_input=body.text,
        status="pending",
    )
    db.add(record)
    db.commit()

    try:
        result = await tts_service.synthesize(
            text=body.text,
            model=model,
            voice=voice_id,
            voice_desc=voice_desc,
            audio_format=body.audio_format,
            optimize_text=body.optimize_text,
            clone_sample_base64=body.clone_sample_base64,
        )

        path, size = storage.save_tts_audio(current.id, record.id, result["audio_bytes"], result["ext"])
        usage = result["usage"] or {}
        latency = int((time.perf_counter() - started) * 1000)

        record.status = "success"
        record.text_final = result["text_final"]
        record.audio_path = path
        record.audio_size = size
        record.audio_mime = result["mime"]
        record.audio_id = result["audio_id"]
        record.prompt_tokens = usage.get("prompt_tokens")
        record.completion_tokens = usage.get("completion_tokens")
        record.total_tokens = usage.get("total_tokens")
        record.latency_ms = latency
        record.request_id = result["request_id"]
        record.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        if body.voice_preset_id:
            preset = db.get(VoicePreset, body.voice_preset_id)
            if preset and preset.user_id == current.id:
                preset.use_count = (preset.use_count or 0) + 1
                preset.last_used_at = record.created_at
                db.commit()

        return {
            "id": record.id,
            "audio_url": f"/api/tts/{record.id}/download",
            "mime": result["mime"],
            "size": size,
            "text_final": result["text_final"],
            "model": result["model"],
            "voice_name": voice_name,
            "latency_ms": latency,
            "usage": usage or None,
            "is_mock": result["is_mock"],
        }

    except AppError as exc:
        db.rollback()
        record.status = "failed"
        record.error_message = exc.message
        record.latency_ms = int((time.perf_counter() - started) * 1000)
        db.commit()
        log.warning("合成失败 user=%s：%s", current.username, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record.status = "failed"
        record.error_message = f"{type(exc).__name__}: {exc}"
        db.commit()
        log.exception("合成未预期失败 user=%s", current.username)
        raise


@router.get("/history", summary="TTS 调用历史")
def history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = select(TTSRecord).where(TTSRecord.user_id == current.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(TTSRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return {"items": [r.to_dict() for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{record_id}/download", summary="下载或在线播放生成的音频")
def download(
    record_id: str,
    disposition: str = Query(default="attachment", pattern="^(inline|attachment)$"),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(TTSRecord, record_id)
    if record is None or record.user_id != current.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    if not record.audio_path:
        raise AppError("该记录没有可下载的音频", code="no_audio", status_code=404)

    data = storage.read_file(record.audio_path)
    if data is None:
        raise AppError("音频文件已被清理或丢失", code="audio_missing", status_code=410)

    filename = f"voice_{record_id}.{record.audio_format or 'wav'}"
    return Response(
        content=data,
        media_type=record.audio_mime or "audio/wav",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/{record_id}", summary="删除一条合成记录及其音频")
def delete(record_id: str, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.get(TTSRecord, record_id)
    if record is None or record.user_id != current.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    storage.delete_file(record.audio_path)
    db.delete(record)
    db.commit()
    return {"ok": True, "id": record_id}
