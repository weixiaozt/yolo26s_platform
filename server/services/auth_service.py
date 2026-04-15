# -*- coding: utf-8 -*-
"""
认证服务：JWT + 密码哈希 + 用户验证
"""

import hashlib
import hmac
import os
import time
import json
import base64
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from ..models.user import User

# ---- 配置 ----
SECRET_KEY = os.environ.get("JWT_SECRET", "yolo26s_seg_platform_secret_key_2024")
TOKEN_EXPIRE_HOURS = 24


# ---- 密码哈希（不依赖 bcrypt，用 PBKDF2）----
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt.hex() + ':' + dk.hex()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_hex, dk_hex = password_hash.split(':')
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ---- JWT（轻量实现，不依赖 pyjwt）----
def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64decode(s: str) -> bytes:
    s += '=' * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def create_token(user_id: int, username: str, role: str) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
    }
    payload = _b64encode(json.dumps(payload_data).encode())
    signature = hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    sig = _b64encode(signature)
    return f"{header}.{payload}.{sig}"


def decode_token(token: str) -> Optional[dict]:
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        # 验证签名
        expected_sig = _b64encode(
            hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            return None
        # 解析 payload
        data = json.loads(_b64decode(payload))
        # 检查过期
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ---- 用户操作 ----
def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_default_admin(db: Session):
    """首次启动时创建默认管理员"""
    admin = db.query(User).filter(User.role == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            display_name="管理员",
            role="admin",
        )
        db.add(admin)
        db.commit()
        print("[认证] 创建默认管理员: admin / admin123")
