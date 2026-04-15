# -*- coding: utf-8 -*-
"""
认证依赖注入：用于路由保护
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models.user import User
from .services.auth_service import decode_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从请求头获取当前登录用户"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")

    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    user = db.query(User).filter(User.id == payload["user_id"], User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """要求管理员权限"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
