"""项目入口：FastAPI 应用装配、全局异常处理、启动流程。

启动方式：
    python main.py
或：
    uvicorn main:app --host 127.0.0.1 --port 8100
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import config
from database import init_db
from routers import admin, auth, tts, user, voice
from routers.deps import Forbidden, AuthRequired, render
from services import task_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mimo")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("服务已启动：http://%s:%s", config.HOST, config.PORT)
    if not config.MIMO_API_KEY:
        log.warning("尚未配置 MIMO_API_KEY，可用默认管理员登录后台 → 系统配置 里填写")
    yield
    task_service.shutdown()
    log.info("服务已停止")


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


# ---------------------------------------------------------------- 全局异常
@app.exception_handler(AuthRequired)
async def _auth_required(request: Request, exc: AuthRequired):
    """未登录访问受保护页面 → 跳登录页，并记住原地址。"""
    return RedirectResponse(f"/login?next={quote(exc.path)}", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, exc: Forbidden):
    return render(request, "error.html", None, code=403, message="没有权限访问该页面")


@app.exception_handler(404)
async def _not_found(request: Request, exc):
    return render(request, "error.html", None, code=404, message="页面不存在")


@app.exception_handler(500)
async def _server_error(request: Request, exc):
    log.exception("服务内部错误：%s", exc)
    return render(request, "error.html", None, code=500, message="服务器出了点问题，请稍后重试")


# ---------------------------------------------------------------- 路由
app.include_router(auth.router)
app.include_router(tts.router)
app.include_router(voice.router)
app.include_router(user.router)
app.include_router(admin.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "app": config.APP_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
