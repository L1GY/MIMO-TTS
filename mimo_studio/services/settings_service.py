"""系统配置读写：数据库里的值优先于 config.py 的默认值。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from config import config
from models import Setting

# 可后台修改的配置项及其默认值
KEYS = {
    "api_key": lambda: config.MIMO_API_KEY,
    "default_quota": lambda: str(config.DEFAULT_QUOTA_CHARS),
    "max_text_len": lambda: str(config.MAX_TEXT_LEN),
    "sensitive_words": lambda: "\n".join(config.SENSITIVE_WORDS),
    "announcement": lambda: "",
}


def get(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row is not None and row.value != "":
        return row.value
    default = KEYS.get(key)
    return default() if default else ""


def get_int(db: Session, key: str, fallback: int = 0) -> int:
    try:
        return int(get(db, key))
    except (TypeError, ValueError):
        return fallback


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def api_key(db: Session) -> str:
    return get(db, "api_key").strip()


def masked_api_key(db: Session) -> str:
    """后台展示用：只露头尾，避免完整密钥出现在页面源码里。"""
    key = api_key(db)
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "*" * (len(key) - 2)
    return f"{key[:6]}{'*' * 8}{key[-4:]}"


def sensitive_words(db: Session) -> list[str]:
    raw = get(db, "sensitive_words")
    # 支持换行 / 英文逗号 / 中文逗号分隔
    for sep in ("\r\n", "\r", "，", ",", "|", " "):
        raw = raw.replace(sep, "\n")
    return [w.strip() for w in raw.split("\n") if w.strip()]


def is_configured(db: Session) -> bool:
    return bool(api_key(db))
