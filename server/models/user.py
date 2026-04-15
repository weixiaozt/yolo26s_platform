# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), default="")
    role = Column(String(20), default="user")  # admin / user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
