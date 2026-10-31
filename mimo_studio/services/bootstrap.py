"""首次启动的种子数据：默认管理员 + 公共音色 + 必要配置。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from config import config
from models import User, Voice
from services.security import hash_password

log = logging.getLogger("mimo.bootstrap")


def seed_initial_data(db: Session) -> None:
    _seed_admin(db)
    _seed_preset_voices(db)


def _seed_admin(db: Session) -> None:
    exists = db.scalar(select(User).where(User.role == "admin"))
    if exists:
        return

    # 若用户名被注册占用，则跳过创建并提示
    if db.scalar(select(User).where(User.username == config.ADMIN_USERNAME)):
        log.warning("用户名 %s 已存在，未能创建默认管理员", config.ADMIN_USERNAME)
        return

    admin = User(
        username=config.ADMIN_USERNAME,
        password_hash=hash_password(config.ADMIN_PASSWORD),
        role="admin",
        is_active=True,
        quota_chars=10 ** 7,
        used_chars=0,
    )
    db.add(admin)
    db.commit()
    log.warning("已创建默认管理员：%s / %s（请登录后立即修改密码）",
                config.ADMIN_USERNAME, config.ADMIN_PASSWORD)


def _seed_preset_voices(db: Session) -> None:
    """按 config.PUBLIC_VOICES 写入公共音色，已存在的只更新名称与描述。"""
    existing = {
        v.voice_key: v
        for v in db.scalars(select(Voice).where(Voice.kind == "preset")).all()
        if v.voice_key
    }

    changed = False
    for item in config.PUBLIC_VOICES:
        key = item["voice_key"]
        voice = existing.get(key)
        if voice is None:
            db.add(Voice(
                kind="preset",
                user_id=None,
                name=item.get("name") or key,
                desc=item.get("desc") or "",
                voice_key=key,
                consent=True,
            ))
            changed = True
        else:
            if voice.name != item.get("name") or (voice.desc or "") != (item.get("desc") or ""):
                voice.name = item.get("name") or key
                voice.desc = item.get("desc") or ""
                changed = True

    if changed:
        db.commit()
        log.info("公共音色已同步，共 %s 个", len(config.PUBLIC_VOICES))
