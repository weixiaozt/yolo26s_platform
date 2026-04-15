# -*- coding: utf-8 -*-
from datetime import datetime

from sqlalchemy import String, Text, Integer, Float, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 预处理参数
    resize_h: Mapped[int] = mapped_column(Integer, default=2048)
    resize_w: Mapped[int] = mapped_column(Integer, default=2048)
    crop_size: Mapped[int] = mapped_column(Integer, default=640)
    overlap: Mapped[float] = mapped_column(Float, default=0.2)

    status: Mapped[str] = mapped_column(
        Enum("active", "archived", name="project_status"),
        default="active"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    defect_classes = relationship("DefectClass", back_populates="project", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="project", cascade="all, delete-orphan")
    train_tasks = relationship("TrainTask", back_populates="project", cascade="all, delete-orphan")
