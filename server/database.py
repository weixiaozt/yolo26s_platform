# -*- coding: utf-8 -*-
"""
数据库引擎与 Session 管理
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """ORM 基类"""
    pass


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """建表 + 自动迁移新字段"""
    from . import models  # noqa
    Base.metadata.create_all(bind=engine)

    # 自动添加新字段（开发阶段简易迁移）
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE images ADD COLUMN mask_path VARCHAR(500) NULL"))
            conn.commit()
            print("[迁移] 已添加 images.mask_path 字段")
        except Exception:
            conn.rollback()  # 字段已存在，忽略
