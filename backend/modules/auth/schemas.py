"""认证模块Schema"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime

from core.time_utils import UtcDatetime
import re


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('密码长度不能少于8位')
        if len(v.encode('utf-8')) > 72:
            raise ValueError('密码不能超过 72 字节（bcrypt 限制）')
        if not re.search(r'[A-Z]', v):
            raise ValueError('密码必须包含大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('密码必须包含小写字母')
        if not re.search(r'\d', v):
            raise ValueError('密码必须包含数字')
        return v

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {'user', 'admin'}
        if v not in allowed:
            raise ValueError(f'角色必须是: {allowed}')
        return v


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    role: str
    is_active: bool
    last_login_at: Optional[UtcDatetime]

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class PasswordChange(BaseModel):
    old_password: str
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('新密码长度不能少于8位')
        if len(v.encode('utf-8')) > 72:
            raise ValueError('新密码不能超过 72 字节（bcrypt 限制）')
        if not re.search(r'[A-Z]', v):
            raise ValueError('新密码必须包含大写字母')
        if not re.search(r'[a-z]', v):
            raise ValueError('新密码必须包含小写字母')
        if not re.search(r'\d', v):
            raise ValueError('新密码必须包含数字')
        return v
