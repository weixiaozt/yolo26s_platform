# -*- coding: utf-8 -*-
from datetime import datetime

from sqlalchemy import (
    Integer, BigInteger, Float, String, Text,
    Enum, DateTime, ForeignKey, JSON, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class TrainTask(Base):
    __tablename__ = "train_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "preparing", "training", "exporting",
             "completed", "failed", "cancelled", name="task_status"),
        default="pending"
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # 训练配置快照（JSON）
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 进度
    epochs: Mapped[int] = mapped_column(Integer, default=0)
    current_epoch: Mapped[int] = mapped_column(Integer, default=0)
    best_map50: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="best.pt 对应 epoch 的 mAP50（与 fitness 同步）",
    )
    best_fitness: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Ultralytics fitness 历史最佳 (0.1·mAP50 + 0.9·mAP50:95)",
    )

    # 模型路径
    best_model_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_model_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    export_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 时间
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关系
    project = relationship("Project", back_populates="train_tasks")
    epoch_logs = relationship("TrainEpochLog", back_populates="task", cascade="all, delete-orphan")


class TrainEpochLog(Base):
    __tablename__ = "train_epoch_logs"
    __table_args__ = (
        Index("idx_task_epoch", "task_id", "epoch"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("train_tasks.id", ondelete="CASCADE"), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)

    # Train Loss
    train_box_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_seg_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_cls_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_dfl_loss: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Val Loss
    val_box_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_seg_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_cls_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_dfl_loss: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 验证指标
    precision_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    map50_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    map50_95_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    map50_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    map50_95_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    lr: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 关系
    task = relationship("TrainTask", back_populates="epoch_logs")
