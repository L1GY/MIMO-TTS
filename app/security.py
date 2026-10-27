"""密码哈希与 JWT 签发/校验。

密码使用 PBKDF2-HMAC-SHA256（stdlib 实现，无编译依赖、无 bcrypt 版本兼容问题），
每条密码独立随机盐，存储格式：pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16


# ---------------------------------------------------------------- 密码


def hash_password(raw: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(raw: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", raw.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001 —— 任何解析失败都视为校验失败
        return False


# ---------------------------------------------------------------- JWT


def create_access_token(user_id: str, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """解码失败时抛出 jwt.PyJWTError，由调用方转换为 401。"""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


# ---------------------------------------------------------------- 校验规则

USERNAME_RE = __import__("re").compile(r"^[A-Za-z0-9_.-]{3,32}$")


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需为 3-32 位字母、数字、下划线、点或短横线")
    return username


def validate_password(password: str) -> str:
    if not password or len(password) < 6:
        raise ValueError("密码至少 6 位")
    if len(password) > 128:
        raise ValueError("密码不能超过 128 位")
    return password
