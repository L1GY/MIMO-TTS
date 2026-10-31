"""Pydantic 参数校验：所有用户输入先过这一层，再进业务逻辑。"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from config import config


# ---------------------------------------------------------------- 账号
class RegisterForm(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=6, max_length=64)
    password2: str = ""
    email: str | None = None

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fa5.-]{3,24}", v):
            raise ValueError("用户名只能包含中英文、数字、下划线、点或短横线，长度 3-24")
        return v

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", v):
            raise ValueError("邮箱格式不正确")
        return v

    def check_password2(self) -> bool:
        return self.password == self.password2


class LoginForm(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


class ChangePasswordForm(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)
    new_password2: str = ""


# ---------------------------------------------------------------- 音色
class VoiceCreateForm(BaseModel):
    name: str = Field(min_length=1, max_length=24)
    desc: str | None = Field(default=None, max_length=100)
    consent: bool = False

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("请填写音色名称")
        return v

    @field_validator("desc")
    @classmethod
    def _clean_desc(cls, v: str | None) -> str | None:
        if not v:
            return None
        return " ".join(v.split())[:100]


class VoiceRenameForm(BaseModel):
    name: str = Field(min_length=1, max_length=24)


# ---------------------------------------------------------------- 合成
class TtsSubmitForm(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str = Field(min_length=1, max_length=32)
    speed: float = 1.0

    @field_validator("text")
    @classmethod
    def _clean_text(cls, v: str) -> str:
        v = (v or "").replace("\r\n", "\n").strip()
        if not v:
            raise ValueError("请输入要合成的文本")
        return v

    @field_validator("speed")
    @classmethod
    def _check_speed(cls, v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 1.0
        return max(config.SPEED_MIN, min(config.SPEED_MAX, v))
