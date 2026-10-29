"""轻量音频后处理：采样率转换、变调、变速。

为什么会需要这个模块：上游语音合成接口只接受文本与音色，并不开放
语速 / 音调 / 采样率参数。为了让界面上的这几个控件不是摆设，这里在拿到
上游返回的 PCM 之后做一层纯 Python 的 DSP 处理，不引入任何第三方依赖。

变换顺序：变调（重采样）→ 变速（OLA 时间拉伸）→ 采样率转换（插值）。
任一步失败都会抛出，由调用方回退到原始音频，绝不阻断主流程。
"""

from __future__ import annotations

import math
import wave
from io import BytesIO

# OLA（Overlap-Add）时间拉伸参数
_WIN = 1024
_HOP = 256


def parse_wav_pcm16(data: bytes) -> tuple[list[float], int] | None:
    """解析 16bit PCM WAV，返回 (单声道浮点样本, 采样率)。

    非 16bit 或非 WAV 时返回 None，交由调用方放弃后处理。
    """
    try:
        with wave.open(BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            rate = w.getframerate()
            n = w.getnframes()
            ch = w.getnchannels()
            raw = w.readframes(n)
    except Exception:  # noqa: BLE001
        return None

    if not raw or n <= 0 or rate <= 0:
        return None

    out: list[float] = []
    step = 2 * ch
    # 多声道取平均混成单声道，后续处理统一按单声道走
    for i in range(0, len(raw) - step + 1, step):
        if ch == 1:
            v = int.from_bytes(raw[i:i + 2], "little", signed=True)
        else:
            total = 0
            for c in range(ch):
                total += int.from_bytes(raw[i + c * 2:i + c * 2 + 2], "little", signed=True)
            v = total / ch
        out.append(v / 32768.0)
    return out, rate


def build_wav_pcm16(samples: list[float], rate: int) -> bytes:
    """把浮点样本写回 16bit 单声道 WAV。"""
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        frames = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            frames += int(v).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _interp_at(x: list[float], pos: float) -> float:
    """线性插值取值，越界返回 0。"""
    i = int(pos)
    if i < 0 or i >= len(x) - 1:
        return x[i] if 0 <= i < len(x) else 0.0
    frac = pos - i
    return x[i] * (1 - frac) + x[i + 1] * frac


def resample_interp(x: list[float], src: int, dst: int) -> list[float]:
    """改变采样率：时长与音高都不变。"""
    if src == dst or not x:
        return list(x)
    n = len(x)
    new_n = max(1, int(round(n * dst / src)))
    ratio = n / new_n
    return [_interp_at(x, i * ratio) for i in range(new_n)]


def pitch_shift(x: list[float], semitones: float) -> list[float]:
    """变调：音高 × k，时长 ÷ k（k = 2^(semitones/12)）。后续用时间拉伸补回时长。"""
    k = 2.0 ** (semitones / 12.0)
    if abs(k - 1.0) < 1e-6 or not x:
        return list(x)
    n = len(x)
    new_n = max(1, int(round(n / k)))
    return [_interp_at(x, i * k) for i in range(new_n)]


def time_stretch(x: list[float], factor: float) -> list[float]:
    """OLA 时间拉伸：时长 × factor，音高不变。"""
    n = len(x)
    if abs(factor - 1.0) < 1e-3 or n < _WIN * 2:
        # 太短或无需处理时退化为按比例重采样（此时会连带音高，但样本过短影响很小）
        if n < _WIN * 2:
            return resample_interp(x, n, max(1, int(round(n * factor))))
        return list(x)

    win = min(_WIN, max(256, n // 8))
    hop = max(64, win // 4)
    syn_hop = max(1, int(round(hop * factor)))

    hann = [0.5 - 0.5 * math.cos(2 * math.pi * i / (win - 1)) for i in range(win)]
    frames = (n - win) // hop + 1
    out_len = max(win, (frames - 1) * syn_hop + win)
    out = [0.0] * out_len
    norm = [0.0] * out_len

    pos = 0
    for f in range(frames):
        base = f * hop
        for j in range(win):
            out[pos + j] += x[base + j] * hann[j]
            norm[pos + j] += hann[j]
        pos += syn_hop

    for i in range(out_len):
        if norm[i] > 1e-8:
            out[i] /= norm[i]
    return out


def apply_effects(data: bytes, *, speed: float = 1.0, pitch: float = 0.0,
                  sample_rate: int | None = None) -> tuple[bytes, dict]:
    """对 WAV 音频施加变速 / 变调 / 采样率转换。

    返回 (音频字节, 实际生效的处理说明)。无法处理时原样返回。
    """
    applied: dict = {}
    parsed = parse_wav_pcm16(data)
    if parsed is None:
        return data, {"skipped": "音频不是 16bit PCM WAV，无法后处理"}

    samples, rate = parsed
    k = 2.0 ** (pitch / 12.0) if pitch else 1.0

    try:
        if abs(pitch) > 1e-6:
            samples = pitch_shift(samples, pitch)
            applied["pitch"] = round(pitch, 2)

        # 无论是否变速都要拉伸：变调已把时长改成 N/k，需要拉伸回目标时长。
        # 拉伸后时长 = (N/k) * f，取 f = k/speed 即得 N/speed —— 音高保持 ×k。
        if abs(k / speed - 1.0) > 1e-3:
            samples = time_stretch(samples, k / speed)
            applied["speed"] = round(speed, 2)

        if sample_rate and sample_rate != rate:
            samples = resample_interp(samples, rate, sample_rate)
            rate = sample_rate
            applied["sample_rate"] = sample_rate

        if not applied:
            return data, {}

        applied["duration"] = round(len(samples) / rate, 2)
        return build_wav_pcm16(samples, rate), applied

    except Exception as exc:  # noqa: BLE001 —— DSP 出问题一律回退原音频
        return data, {"skipped": f"音频后处理失败，已使用原始音频：{exc}"}
