"""密码哈希（bcrypt）与 Cookie 签名会话（itsdangerous）。"""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import config

# URLSafeTimedSerializer 会把数据签名后放进 Cookie，不依赖任何服务端存储
_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt=config.SESSION_SALT)


# ---------------------------------------------------------------- 密码
def hash_password(password: str) -> str:
    """bcrypt 哈希。bcrypt 只处理前 72 字节，超长密码先截断避免异常。"""
    import bcrypt

    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    import bcrypt

    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- 会话
def create_session_token(user_id: str) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str | None) -> str | None:
    """校验签名与有效期，返回 user_id；任何异常都视为未登录。"""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=config.SESSION_MAX_AGE)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    return str(uid) if uid else None


def client_ip(request) -> str:
    """取真实客户端 IP（本机部署通常没有代理，直接取 client.host）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]
