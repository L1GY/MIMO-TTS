"""SQLite 连接与 ORM 初始化。首次启动自动建库建表并写入种子数据。"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import config

log = logging.getLogger("mimo.db")

# check_same_thread=False：线程池里的工作线程也要用同一个 SQLite 文件
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _record):
    """WAL 模式让读写并发更稳，外键约束默认是关的必须显式打开。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """所有模型的基类。"""


def get_db():
    """FastAPI 依赖：每个请求一个会话，结束后关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表 + 初始化目录 + 种子数据（管理员、公共音色）。"""
    from models import (  # noqa: F401  确保模型已注册到 metadata
        OpLog, Setting, Task, User, Voice,
    )

    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)

    from services.bootstrap import seed_initial_data

    with SessionLocal() as db:
        seed_initial_data(db)

    log.info("数据库就绪：%s", config.DB_PATH)
