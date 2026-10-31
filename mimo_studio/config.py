"""
全局配置。

替换 API Key 的位置：
  1) 推荐：项目根目录新建 .env 文件，写入 MIMO_API_KEY=sk-xxxx（见 .env.example）
  2) 或在系统环境变量中设置 MIMO_API_KEY
  3) 或启动后在「管理后台 → 系统配置」页面修改（写入数据库，优先级最高）

数据库中的配置会覆盖这里的默认值，前端永远拿不到 API Key。
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """极简 .env 读取，避免为此引入额外依赖。"""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # 真实环境变量优先，不被 .env 覆盖
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class Config:
    BASE_DIR = BASE_DIR  # 项目根目录，模板等相对路径都以它为基准

    # ------------------------------------------------------------ 应用
    APP_NAME = "MiMo 声音工坊"
    APP_SUBTITLE = "文字转语音 · 声音克隆"
    HOST = _env("HOST", "127.0.0.1")
    PORT = _env_int("PORT", 8100)

    # ------------------------------------------------------------ 安全与会话
    # 生产环境请通过环境变量 SECRET_KEY 覆盖（改了会让所有登录态失效）
    SECRET_KEY = _env("SECRET_KEY", "") or secrets.token_urlsafe(32)
    SESSION_COOKIE = "mimo_session"
    SESSION_SALT = "mimo.session.v1"
    SESSION_MAX_AGE = _env_int("SESSION_MAX_AGE", 7 * 24 * 3600)  # 7 天
    COOKIE_SECURE = _env("COOKIE_SECURE", "0") == "1"  # 部署到 https 时设 1

    # ------------------------------------------------------------ 数据库
    DB_PATH = Path(_env("DB_PATH", str(BASE_DIR / "mimo.db")))
    DATABASE_URL = f"sqlite:///{DB_PATH}"

    # ------------------------------------------------------------ 文件存储
    STATIC_DIR = BASE_DIR / "static"
    AUDIO_DIR = STATIC_DIR / "audio"
    SAMPLE_DIR = AUDIO_DIR / "samples"   # 用户上传的音色样本
    OUTPUT_DIR = AUDIO_DIR / "outputs"   # 合成结果

    # ------------------------------------------------------------ MiMo 官方 API
    # 注意：messages 必须包含 role=assistant（官方 400 明确要求），
    #       克隆模型的 audio.voice 必须是 DataURL，不是裸 base64。
    MIMO_API_BASE = _env("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
    MIMO_API_KEY = _env("MIMO_API_KEY", "")
    TTS_MODEL = _env("TTS_MODEL", "mimo-v2.5-tts")
    CLONE_MODEL = _env("CLONE_MODEL", "mimo-v2.5-tts-voiceclone")
    API_TIMEOUT = _env_int("API_TIMEOUT", 120)
    API_MAX_RETRIES = _env_int("API_MAX_RETRIES", 3)

    # ------------------------------------------------------------ 业务规则
    DEFAULT_QUOTA_CHARS = _env_int("DEFAULT_QUOTA_CHARS", 20000)  # 新用户赠送字数
    MAX_TEXT_LEN = _env_int("MAX_TEXT_LEN", 3000)                 # 单次提交上限
    CHUNK_MAX_CHARS = _env_int("CHUNK_MAX_CHARS", 280)            # 分段合成阈值
    SPEED_MIN = 0.5
    SPEED_MAX = 2.0
    AUDIO_FORMAT = "mp3"

    SAMPLE_MIN_SECONDS = 3
    SAMPLE_MAX_SECONDS = 10
    SAMPLE_MAX_MB = 10
    SAMPLE_ALLOWED_EXT = {".wav", ".mp3"}

    # ------------------------------------------------------------ 默认管理员
    ADMIN_USERNAME = _env("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "admin123")

    # ------------------------------------------------------------ 后台线程池
    WORKER_THREADS = _env_int("WORKER_THREADS", 2)

    # ------------------------------------------------------------ 公共音色（MiMo 官方预置）
    # 想增加公共音色：在下面追加一项即可，首次启动会自动写入数据库；
    # IDs 必须是官方音色标识，name/desc 可自由自定义。
    PUBLIC_VOICES: list[dict] = [
        {"voice_key": "mimo_default", "name": "默认音色", "desc": "自然均衡，通用播报"},
        {"voice_key": "冰糖", "name": "冰糖", "desc": "清亮甜美，少女感"},
        {"voice_key": "茉莉", "name": "茉莉", "desc": "温柔知性，适合旁白"},
        {"voice_key": "苏打", "name": "苏打", "desc": "活泼轻快，带气泡感"},
        {"voice_key": "白桦", "name": "白桦", "desc": "沉稳清冽，男声"},
        {"voice_key": "Mia", "name": "Mia", "desc": "英文女声，自然口语"},
        {"voice_key": "Chloe", "name": "Chloe", "desc": "英文女声，知性冷静"},
        {"voice_key": "Milo", "name": "Milo", "desc": "英文男声，年轻活力"},
        {"voice_key": "Dean", "name": "Dean", "desc": "英文男声，低沉稳重"},
    ]

    # ------------------------------------------------------------ 敏感词（可在后台修改）
    SENSITIVE_WORDS: list[str] = [
        "法轮功", "六四事件", "毒品交易", "制毒", "枪支买卖",
    ]


config = Config()
