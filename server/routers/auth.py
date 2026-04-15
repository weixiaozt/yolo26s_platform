# -*- coding: utf-8 -*-
"""
认证 API：登录、用户管理
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..services.auth_service import (
    authenticate_user, create_token, hash_password,
)
from ..deps import get_current_user, require_admin

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=4, max_length=100)
    display_name: str = Field(default="", max_length=100)
    role: str = Field(default="user")  # admin / user


class UserUpdate(BaseModel):
    display_name: str = None
    role: str = None
    is_active: bool = None


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(min_length=4, max_length=100)


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """用户登录，返回 JWT token"""
    user = authenticate_user(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(user.id, user.username, user.role)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
        },
    }


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


@router.put("/me/password")
def change_my_password(req: ChangePassword, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """修改自己的密码"""
    from ..services.auth_service import verify_password
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"ok": True, "message": "密码已修改"}


# ---- 管理员接口 ----

@router.get("/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """列出所有用户（管理员）"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users")
def create_user(req: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """创建用户（管理员）"""
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"用户名 {req.username} 已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name or req.username,
        role=req.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username, "message": "用户已创建"}


@router.put("/users/{user_id}")
def update_user(user_id: int, req: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """修改用户信息（管理员）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.role is not None:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """重置用户密码为 123456（管理员）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password("123456")
    db.commit()
    return {"ok": True, "message": f"密码已重置为 123456"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """删除用户（管理员）"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        admin_count = db.query(User).filter(User.role == "admin", User.is_active == True).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员")
    db.delete(user)
    db.commit()
    return {"ok": True}
