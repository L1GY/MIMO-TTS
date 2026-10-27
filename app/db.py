"""数据库引擎、会话与基类。使用 SQLite，文件位置由 DATABASE_URL 决定。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def _ensure_parent_dir(url: str) -> None:
    """确保 SQLite 数据库文件所在目录存在。"""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        raw = url[len(prefix):]
        if raw and raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)


_ensure_parent_dir(settings.database_url)

# check_same_thread=False：FastAPI 会在不同线程中复用同一个连接
engine: Engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover
    """开启外键约束与 WAL，提高并发写入表现。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """ORM 声明基类。"""


# SQLite 类型映射，用于缺列时自动补列
_SQLITE_TYPES = {
    "str": "TEXT",
    "text": "TEXT",
    "int": "INTEGER",
    "integer": "INTEGER",
    "float": "REAL",
    "bool": "BOOLEAN",
    "datetime": "DATETIME",
}


def ensure_columns() -> None:
    """为已存在的表补齐新增字段，避免旧库升级后报错。

    SQLite 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS，这里比对元数据后按需补列。
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        with engine.begin() as conn:
            for col in table.columns:
                if col.name in existing:
                    continue
                try:
                    coltype = _SQLITE_TYPES.get(str(col.type).lower(), "TEXT")
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
                except Exception:  # noqa: BLE001
                    # 补列失败不阻断启动，后续 create_all 与业务会暴露具体问题
                    pass


def get_db():
    """FastAPI 依赖：提供数据库会话，请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
