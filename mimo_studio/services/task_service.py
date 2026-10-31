"""异步任务调度：ThreadPoolExecutor + 数据库状态轮询（不依赖 Redis / Celery）。

流程：
  queued → running（开始合成，逐段更新进度）→ success / failed
失败时自动退回已扣的额度，并把原因写进 task.error 供前端展示。
"""
from __future__ import annotations

import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import config
from database import SessionLocal
from models import OpLog, Task, User, Voice
from models.base import now
from services import audio_service, mimo_api, settings_service, text_utils

log = logging.getLogger("mimo.task")

# 单进程内的线程池；进程退出时随进程销毁，任务状态都在数据库里，不怕重启
_executor = ThreadPoolExecutor(
    max_workers=max(1, config.WORKER_THREADS),
    thread_name_prefix="mimo-tts",
)


def submit(task_id: str) -> None:
    """把任务丢进线程池，立即返回。"""
    _executor.submit(_run_task, task_id)


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------- 内部
def _abs_sample(voice: Voice) -> str:
    return str(config.STATIC_DIR / (voice.sample_path or ""))


def _synthesize_chunk(text: str, voice: Voice, speed: float, api_key: str) -> bytes:
    if voice.kind == "clone":
        return mimo_api.synthesis_clone_tts(text, _abs_sample(voice), speed, api_key)
    # 预置音色：voice_key 是官方音色标识
    return mimo_api.synthesis_tts(text, voice.voice_key or "mimo_default", speed, api_key)


def _refund_quota(db, task: Task) -> None:
    user = db.get(User, task.user_id)
    if not user:
        return
    user.used_chars = max(0, int(user.used_chars) - int(task.text_len or 0))
    db.commit()


def _log(db, task: Task, action: str, detail: str) -> None:
    user = db.get(User, task.user_id)
    db.add(OpLog(
        user_id=task.user_id,
        username=user.username if user else "",
        action=action,
        detail=detail[:800],
        ip="system",
    ))
    db.commit()


def _run_task(task_id: str) -> None:
    db = SessionLocal()
    temp_files: list = []
    try:
        task = db.get(Task, task_id)
        if not task:
            log.warning("任务不存在：%s", task_id)
            return
        if task.status in ("success", "running"):
            return

        task.mark_running()
        db.commit()

        voice = db.get(Voice, task.voice_id) if task.voice_id else None
        if voice is None:
            raise mimo_api.MimoError("所选音色已不存在，请重新选择", "voice_missing")
        if voice.kind == "clone" and not voice.sample_path:
            raise mimo_api.MimoError("音色样本丢失，请重新上传该音色", "sample_missing")
        if voice.status == "blocked":
            raise mimo_api.MimoError("该音色已被管理员下架，无法使用", "voice_blocked")

        api_key = settings_service.api_key(db)
        chunks = text_utils.split_chunks(task.text, config.CHUNK_MAX_CHARS)
        if not chunks:
            raise mimo_api.MimoError("没有可合成的文本", "empty_text")

        task.total_chunks = len(chunks)
        task.done_chunks = 0
        task.progress = 5
        db.commit()

        parts = []
        for index, chunk in enumerate(chunks, start=1):
            data = _synthesize_chunk(chunk, voice, task.speed, api_key)
            part = audio_service.temp_path(".mp3")
            part.write_bytes(data)
            parts.append(part)
            temp_files.append(part)

            task.done_chunks = index
            # 5% ~ 90% 之间按分段进度推进
            task.progress = 5 + int(index / len(chunks) * 85)
            db.commit()
            log.info("任务 %s 第 %s/%s 段完成", task.id, index, len(chunks))

        merged = audio_service.temp_path(".mp3")
        audio_service.concat(parts, merged, "mp3")

        final_name = f"{uuid.uuid4().hex}.mp3"
        final_abs = config.OUTPUT_DIR / final_name
        final_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(merged), str(final_abs))

        task.result_path = final_abs.relative_to(config.STATIC_DIR).as_posix()
        task.result_size = final_abs.stat().st_size
        try:
            task.duration = audio_service.mp3_duration(final_abs)
        except audio_service.AudioError:
            task.duration = None
        task.status = "success"
        task.progress = 100
        task.finished_at = now()
        task.error = None
        db.commit()

        _log(db, task, "tts.success",
             f"任务 {task.id} 完成，{len(chunks)} 段，{task.text_len} 字，音色 {task.voice_name}")

    except mimo_api.MimoError as exc:
        _fail(db, task_id, exc.message)
        log.warning("任务失败 %s：%s", task_id, exc.message)
    except audio_service.AudioError as exc:
        _fail(db, task_id, f"音频处理失败：{exc}")
        log.warning("任务音频处理失败 %s：%s", task_id, exc)
    except Exception as exc:  # noqa: BLE001
        _fail(db, task_id, f"未预期的错误：{type(exc).__name__}: {exc}")
        log.exception("任务异常 %s", task_id)
    finally:
        audio_service.cleanup(temp_files)
        db.close()


def _fail(db, task_id: str, message: str) -> None:
    try:
        db.rollback()
        task = db.get(Task, task_id)
        if not task:
            return
        task.mark_failed(message)
        db.commit()
        _refund_quota(db, task)
        _log(db, task, "tts.failed", f"任务 {task.id} 失败：{message}")
    except Exception:  # noqa: BLE001
        log.exception("记录失败状态时出错 %s", task_id)
