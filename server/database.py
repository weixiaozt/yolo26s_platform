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
    migrations = [
        ("ALTER TABLE images ADD COLUMN mask_path VARCHAR(500) NULL", "images.mask_path"),
        (
            "ALTER TABLE projects ADD COLUMN task_type ENUM('seg','det') NOT NULL DEFAULT 'seg' "
            "COMMENT '任务类型: seg=分割, det=目标检测'",
            "projects.task_type",
        ),
    ]
    for sql, label in migrations:
        with engine.connect() as conn:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"[迁移] 已添加 {label} 字段")
            except Exception:
                conn.rollback()  # 字段已存在，忽略
