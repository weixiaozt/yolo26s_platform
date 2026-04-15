# -*- coding: utf-8 -*-
from datetime import datetime

from sqlalchemy import String, Integer, BigInteger, Float, Enum, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        Index("idx_project_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    filename: Mapped[str] = mapped_column(String(300), nullable=False, comment="原始文件名")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="相对于 storage/uploads 的路径")
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="缩略图路径")
    mask_path: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="标注mask路径")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)

    status: Mapped[str] = mapped_column(
        Enum("unlabeled", "labeling", "labeled", "reviewed", name="image_status"),
        default="unlabeled"
    )
    annotator: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关系
    project = relationship("Project", back_populates="images")
    annotations = relationship("Annotation", back_populates="image", cascade="all, delete-orphan")
