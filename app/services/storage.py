"""音频与上传文件的落盘存储管理。

目录结构：
    data/audio/{user_id}/{record_id}.{ext}     —— TTS 生成的音频
    data/uploads/{user_id}/{record_id}_{filename}  —— ASR 上传的音频归档
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from ..config import settings

_SAFE_RE = re.compile(r"[^\w.\-]+", re.UNICODE)


def _safe_name(name: str, limit: int = 60) -> str:
    """清洗文件名，防止路径穿越与非法字符。"""
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _SAFE_RE.sub("_", name).strip("._")
    return (name or "file")[:limit]


def ensure_dirs() -> None:
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


def save_tts_audio(user_id: str, record_id: str, data: bytes, ext: str) -> tuple[str, int]:
    """保存 TTS 音频，返回 (绝对路径, 字节数)。"""
    target_dir = Path(settings.audio_dir) / user_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{record_id}.{ext.lstrip('.')}"
    path.write_bytes(data)
    return str(path.resolve()), len(data)


def save_upload(user_id: str, record_id: str, filename: str, data: bytes) -> tuple[str, int]:
    target_dir = Path(settings.upload_dir) / user_id
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{record_id}_{_safe_name(filename)}"
    path.write_bytes(data)
    return str(path.resolve()), len(data)


def delete_file(path: str | None) -> bool:
    """删除文件，忽略不存在的情况。返回是否真的删除了。"""
    if not path:
        return False
    try:
        p = Path(path)
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        return False
    return False


def read_file(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        p = Path(path)
        if p.is_file():
            return p.read_bytes()
    except OSError:
        return None
    return None


def free_bytes(path: str) -> int:
    return os.path.getsize(path) if path and os.path.exists(path) else 0
