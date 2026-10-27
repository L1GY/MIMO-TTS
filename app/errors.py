"""统一异常与错误响应。

所有接口错误统一返回：
    HTTP/1.1 <status>
    {"error": {"code": "xxx", "message": "可读的中文提示", "detail": "可选的技术细节"}}

其中 code 为稳定枚举，前端据此做差异化提示。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, detail: Any = None,
                 status_code: int | None = None):
        self.message = message
        self.detail = detail
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(message)


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ConfigError(AppError):
    status_code = 503
    code = "not_configured"


class UpstreamError(AppError):
    """调用上游语音服务失败。status_code 由具体映射决定。"""

    status_code = 502
    code = "upstream_error"


class RateLimitError(UpstreamError):
    status_code = 429
    code = "upstream_rate_limited"


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保证任何异常都返回结构化 JSON。"""

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        body: dict[str, Any] = {"error": {"code": exc.code, "message": exc.message}}
        if exc.detail:
            body["error"]["detail"] = str(exc.detail)[:1000]
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail)}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # 提取第一个字段错误，给出可读提示
        errors = exc.errors()
        hint = ""
        if errors:
            loc = ".".join(str(x) for x in errors[0].get("loc", []) if x != "body")
            hint = f"字段 {loc} 校验失败：{errors[0].get('msg', '')}" if loc else str(errors[0].get("msg", ""))

        # 精简后回传：ctx 中可能带有异常对象，input 可能很大，都不能直接 JSON 序列化
        simplified = []
        for e in errors[:10]:
            simplified.append(
                {
                    "loc": [str(x) for x in e.get("loc", [])],
                    "msg": str(e.get("msg", "")),
                    "type": str(e.get("type", "")),
                }
            )

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": hint or "请求参数不合法",
                    "detail": simplified,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # 兜底：记录到日志，不向客户端暴露堆栈
        import logging

        logging.getLogger("voice_atelier").exception("未处理异常：%s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "服务器内部错误，请稍后重试"}},
        )
