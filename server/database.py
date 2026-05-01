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
        (
            "ALTER TABLE train_tasks ADD COLUMN best_fitness FLOAT NULL "
            "COMMENT 'Ultralytics fitness 最佳值（与 best.pt 同步）'",
            "train_tasks.best_fitness",
        ),
        # 扩展 task_type ENUM 加 cls
        (
            "ALTER TABLE projects MODIFY COLUMN task_type ENUM('seg','det','cls') "
            "NOT NULL DEFAULT 'seg' COMMENT '任务类型: seg=分割, det=目标检测, cls=图像分类'",
            "projects.task_type 扩展 cls",
        ),
        (
            "ALTER TABLE images ADD COLUMN class_id INT NULL "
            "COMMENT '分类项目专用：图级分类的类别 id'",
            "images.class_id",
        ),
        (
            "ALTER TABLE images ADD CONSTRAINT fk_images_class_id "
            "FOREIGN KEY (class_id) REFERENCES defect_classes(id) ON DELETE SET NULL",
            "images.class_id 外键",
        ),
        (
            "CREATE INDEX idx_images_class_id ON images(class_id)",
            "images.class_id 索引",
        ),
        (
            "ALTER TABLE train_epoch_logs ADD COLUMN top1_acc FLOAT NULL COMMENT 'cls top1'",
            "train_epoch_logs.top1_acc",
        ),
        (
            "ALTER TABLE train_epoch_logs ADD COLUMN top5_acc FLOAT NULL COMMENT 'cls top5'",
            "train_epoch_logs.top5_acc",
        ),
        # 扩展 task_type ENUM 加 obb（旋转目标检测）
        (
            "ALTER TABLE projects MODIFY COLUMN task_type ENUM('seg','det','cls','obb') "
            "NOT NULL DEFAULT 'seg' COMMENT '任务类型: seg=分割, det=目标检测, cls=图像分类, obb=旋转目标检测'",
            "projects.task_type 扩展 obb",
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
