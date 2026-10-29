"""创建并配置 FastAPI 应用。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings, APP_NAME
from .db import Base, engine, ensure_columns
from .errors import register_exception_handlers
from .routers import asr, auth, history, meta, tts, voices
from .services import storage

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
log = logging.getLogger("voice_atelier")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：建目录、建表
    storage.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_columns()  # 旧库补齐新增字段
    mode = "在线（真实调用上游语音服务）" if settings.live_mode else "模拟模式（未真实调用上游）"
    log.info("%s 启动完成，运行模式：%s", APP_NAME, mode)
    log.info("数据库：%s", settings.database_url)

    ready, missing = settings.upstream_ready()
    if not ready:
        log.error("上游配置不完整，缺：%s —— 请对照 .env.example 补齐", "、".join(missing))
    if not settings.wechat_enabled:
        log.info("微信登录未配置，已自动关闭（账号密码登录不受影响）")
    yield
    log.info("服务已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title="声坊 Voice Atelier",
        description="文本转语音、音色设计与语音识别工作台",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(tts.router)
    app.include_router(asr.router)
    app.include_router(history.router)
    app.include_router(voices.router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg")

    @app.get("/__tcb_probe__")
    def tcb_probe():
        return {"status": "ok"}


    return app


app = create_app()
