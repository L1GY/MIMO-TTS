"""ASR 路由：上传音频转文字、历史、源音频下载与删除。全部要求登录。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ASR_INPUT_FORMATS, ASR_LANGUAGES, settings
from ..db import get_db
from ..deps import get_current_user
from ..errors import AppError
from ..models import ASRRecord, User
from ..services import asr_service, storage

log = logging.getLogger("voice_atelier.asr_api")
router = APIRouter(prefix="/api/asr", tags=["asr"])


@router.get("/options", summary="ASR 可选项与限制")
def options(_: User = Depends(get_current_user)):
    return {
        "languages": ASR_LANGUAGES,
        "formats": [{"id": k, "mime": v} for k, v in ASR_INPUT_FORMATS.items()],
        "model": settings.asr_model,
        "max_upload_mb": settings.max_upload_mb,
    }


def _sniff_format(filename: str, content_type: str | None) -> str:
    """根据扩展名 / MIME 判定音频格式，只接受 wav 与 mp3。"""
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext in ASR_INPUT_FORMATS:
        return ext
    ct = (content_type or "").lower()
    if "mpeg" in ct or "mp3" in ct:
        return "mp3"
    if "wav" in ct or "x-wav" in ct or "wave" in ct:
        return "wav"
    raise AppError("仅支持 wav 或 mp3 格式的音频文件", code="unsupported_audio_format")


def _to_bool(v: str | None, default: bool = False) -> bool:
    """multipart 的 form 字段都是字符串，这里统一转成布尔。"""
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _split_segments(text: str) -> list[str]:
    """把识别结果按句切分成段落（上游不提供分段参数，由服务端后处理实现）。"""
    import re

    parts = re.split(r"(?<=[。！？!?；;])", text)
    return [p.strip() for p in parts if p and p.strip()]


@router.post("/transcribe", summary="上传音频转文字")
async def transcribe(
    file: UploadFile = File(..., description="wav / mp3 音频文件"),
    language: str = Form(default="auto"),
    punctuate: str = Form(default="true"),
    segment: str = Form(default="false"),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if language not in {"auto", "zh", "en"}:
        raise AppError("language 仅支持 auto / zh / en", code="invalid_language")

    want_punctuate = _to_bool(punctuate, True)
    want_segment = _to_bool(segment, False)

    fmt = _sniff_format(file.filename or "", file.content_type)
    mime = ASR_INPUT_FORMATS[fmt]

    data = await file.read()
    if not data:
        raise AppError("上传的音频文件为空", code="empty_file")
    if len(data) > settings.max_upload_bytes:
        raise AppError(
            f"音频体积超过上限（{settings.max_upload_mb}MB）。"
            "官方要求 base64 编码后不超过 10MB，请压缩或裁剪后再试",
            code="file_too_large",
            status_code=413,
        )
    if len(data) > int(settings.max_upload_bytes * 0.75):
        # base64 后体积约为原始的 1.33 倍，接近 10MB 上限时提前提示
        log.info("音频接近上限：%s 字节", len(data))

    started = time.perf_counter()
    record = ASRRecord(
        user_id=current.id,
        model=settings.asr_model,
        language=language,
        punctuate=want_punctuate,
        segment=want_segment,
        filename=file.filename,
        file_size=len(data),
        file_mime=mime,
        status="pending",
    )
    db.add(record)
    db.commit()

    try:
        stored_path, _ = storage.save_upload(current.id, record.id, file.filename or f"audio.{fmt}", data)
        result = await asr_service.transcribe(data=data, fmt=fmt, language=language)
        usage = result["usage"] or {}
        latency = int((time.perf_counter() - started) * 1000)

        transcript = result["transcript"]
        if not want_punctuate:
            # 上游本身就会输出标点，关闭时由这里去掉（含中英文标点）
            import re

            transcript = re.sub(r"[，。！？；：、,.!?;:]", "", transcript).strip()

        segments = _split_segments(transcript) if want_segment else None

        record.status = "success"
        record.transcript = transcript
        record.stored_path = stored_path
        record.audio_seconds = result["seconds"]
        record.prompt_tokens = usage.get("prompt_tokens")
        record.completion_tokens = usage.get("completion_tokens")
        record.total_tokens = usage.get("total_tokens")
        record.latency_ms = latency
        record.request_id = result["request_id"]
        record.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        return {
            "id": record.id,
            "transcript": transcript,
            "segments": segments,
            "model": result["model"],
            "language": language,
            "audio_seconds": result["seconds"],
            "audio_url": f"/api/asr/{record.id}/download",
            "filename": record.filename,
            "file_size": record.file_size,
            "latency_ms": latency,
            "usage": usage or None,
            "is_mock": result["is_mock"],
            "created_at": record.created_at.isoformat() + "Z",
        }

    except AppError as exc:
        db.rollback()
        record.status = "failed"
        record.error_message = exc.message
        record.latency_ms = int((time.perf_counter() - started) * 1000)
        db.commit()
        log.warning("ASR 失败 user=%s：%s", current.username, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record.status = "failed"
        record.error_message = f"{type(exc).__name__}: {exc}"
        db.commit()
        log.exception("ASR 未预期失败 user=%s", current.username)
        raise


@router.get("/history", summary="ASR 调用历史")
def history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = select(ASRRecord).where(ASRRecord.user_id == current.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(ASRRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return {"items": [r.to_dict() for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{record_id}/download", summary="下载上传的源音频")
def download(
    record_id: str,
    disposition: str = Query(default="attachment", pattern="^(inline|attachment)$"),
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.get(ASRRecord, record_id)
    if record is None or record.user_id != current.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    data = storage.read_file(record.stored_path)
    if data is None:
        raise AppError("源音频已被清理或丢失", code="audio_missing", status_code=410)

    safe = (record.filename or "audio").replace('"', "")
    return Response(
        content=data,
        media_type=record.file_mime or "audio/wav",
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe}"',
            "Content-Length": str(len(data)),
        },
    )


@router.delete("/{record_id}", summary="删除一条 ASR 记录及其音频")
def delete(record_id: str, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.get(ASRRecord, record_id)
    if record is None or record.user_id != current.id:
        raise HTTPException(status_code=404, detail="记录不存在")
    storage.delete_file(record.stored_path)
    db.delete(record)
    db.commit()
    return {"ok": True, "id": record_id}
