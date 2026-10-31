"""音频处理：时长探测、格式校验、分段拼接、文件落盘与清理。

不依赖 ffmpeg / pydub：
  · 时长：wav 读头部，mp3 逐帧解析（MPEG1/2/2.5 Layer III）
  · 拼接：mp3 去掉 ID3 后按帧顺序拼接；wav 重写 RIFF 头
这样单机部署不需要额外装系统组件。
"""
from __future__ import annotations

import logging
import os
import uuid
import wave
from pathlib import Path

from config import config

log = logging.getLogger("mimo.audio")

# ---------------------------------------------------------------- MPEG 查表
_BR_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]     # kbps
_BR_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_SR = {3: [44100, 48000, 32000, 0], 2: [22050, 24000, 16000, 0], 0: [11025, 12000, 8000, 0]}
_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


class AudioError(Exception):
    """音频处理相关的可读错误。"""


# ---------------------------------------------------------------- 工具
def human_size(size: int | None) -> str:
    if not size:
        return "—"
    mb = size / 1024 / 1024
    return f"{mb:.2f} MB" if mb >= 1 else f"{size / 1024:.0f} KB"


def ext_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def mime_of(ext: str) -> str:
    return _MIME.get(ext, "audio/mpeg")


def _syncsafe(b: bytes) -> int:
    return (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)


def _strip_id3(data: bytes) -> bytes:
    """去掉 ID3v2 头与 ID3v1 尾，保证拼接出来的 mp3 中间没有标签块。"""
    if data[:3] == b"ID3" and len(data) > 10:
        size = _syncsafe(data[6:10])
        data = data[10 + size:]
    if data[-128:-125] == b"TAG":
        data = data[:-128]
    return data


# ---------------------------------------------------------------- 时长
def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate() or 1
        return w.getnframes() / float(rate)


def mp3_duration(path: str | Path) -> float:
    """逐帧解析，CBR / VBR 都适用。"""
    data = Path(path).read_bytes()
    pos = 0
    if data[:3] == b"ID3" and len(data) > 10:
        pos = 10 + _syncsafe(data[6:10])

    total = 0.0
    frames = 0
    n = len(data)
    while pos + 4 <= n:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        b1, b2 = data[pos + 1], data[pos + 2]
        version = (b1 >> 3) & 0x03      # 3=MPEG1 2=MPEG2 0=MPEG2.5
        layer = (b1 >> 1) & 0x03        # 1=Layer III
        br_idx = (b2 >> 4) & 0x0F
        sr_idx = (b2 >> 2) & 0x03
        padding = (b2 >> 1) & 0x01

        if version == 1 or layer != 1 or br_idx in (0, 15) or sr_idx == 3:
            pos += 1
            continue

        bitrate = (_BR_V1_L3 if version == 3 else _BR_V2_L3)[br_idx] * 1000
        sample_rate = _SR[version][sr_idx]
        if not bitrate or not sample_rate:
            pos += 1
            continue

        samples_per_frame = 1152 if version == 3 else 576
        frame_len = (144 if version == 3 else 72) * bitrate // sample_rate + padding
        if frame_len <= 4:
            pos += 1
            continue

        total += samples_per_frame / sample_rate
        frames += 1
        pos += frame_len

    if frames == 0:
        raise AudioError("无法解析该 mp3 文件的时长，请换一个文件或转成 wav 再上传")
    return total


def probe_duration(path: str | Path) -> float:
    ext = ext_of(str(path))
    if ext == ".wav":
        return wav_duration(path)
    if ext == ".mp3":
        return mp3_duration(path)
    raise AudioError("仅支持 wav / mp3 格式")


# ---------------------------------------------------------------- 保存上传
def save_sample(data: bytes, filename: str) -> tuple[str, Path]:
    """保存用户上传的音色样本，返回 (相对 static 的路径, 绝对路径)。"""
    ext = ext_of(filename)
    if ext not in config.SAMPLE_ALLOWED_EXT:
        raise AudioError("仅支持 wav / mp3 格式的音频")

    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = config.SAMPLE_DIR / name
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)

    # 统一用正斜杠，便于拼 URL
    rel = abs_path.relative_to(config.STATIC_DIR).as_posix()
    return rel, abs_path


def temp_path(suffix: str = ".mp3") -> Path:
    return config.OUTPUT_DIR / f"tmp_{uuid.uuid4().hex}{suffix}"


# ---------------------------------------------------------------- 拼接
def concat_mp3(parts: list[str | Path], out_path: str | Path) -> None:
    """按帧顺序拼接 mp3（去掉每段的 ID3 标签，接缝处不会有静音或爆音）。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        for p in parts:
            data = _strip_id3(Path(p).read_bytes())
            if not data:
                continue
            fh.write(data)
    if out.stat().st_size == 0:
        raise AudioError("音频片段为空，拼接失败")


def concat_wav(parts: list[str | Path], out_path: str | Path) -> None:
    """wav 拼接：参数必须一致，重写 RIFF 头。"""
    out = Path(out_path)
    frames = bytearray()
    params = None
    for p in parts:
        with wave.open(str(p), "rb") as w:
            cur = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if params is None:
                params = cur
            elif cur != params:
                raise AudioError("各段音频参数不一致，无法拼接为单个 wav")
            frames += w.readframes(w.getnframes())
    if params is None:
        raise AudioError("没有可拼接的音频片段")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(params[1])
        w.setframerate(params[2])
        w.writeframes(bytes(frames))


def concat(parts: list[str | Path], out_path: str | Path, ext: str = "mp3") -> None:
    if ext == "wav":
        concat_wav(parts, out_path)
    else:
        concat_mp3(parts, out_path)


# ---------------------------------------------------------------- 清理
def delete_static_file(rel_path: str | None) -> None:
    """删除 static 下的文件。带路径校验，避免越权删到项目外。"""
    if not rel_path:
        return
    target = (config.STATIC_DIR / rel_path).resolve()
    try:
        target.relative_to(config.STATIC_DIR.resolve())
    except ValueError:
        log.warning("拒绝删除 static 之外的路径：%s", rel_path)
        return
    try:
        if target.is_file():
            target.unlink()
    except OSError as exc:
        log.warning("删除文件失败 %s：%s", target, exc)


def cleanup(paths: list[str | Path]) -> None:
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
