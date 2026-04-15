# -*- coding: utf-8 -*-
from datetime import datetime

from sqlalchemy import Integer, Float, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey("defect_classes.id"), nullable=False)

    # 多边形坐标（归一化 0~1）: [{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}, ...]
    polygon: Mapped[list] = mapped_column(JSON, nullable=False)

    # 冗余字段：便于统计和过滤
    area: Mapped[float | None] = mapped_column(Float, nullable=True, comment="多边形面积(像素)")
    bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment='外接矩形 {"x1","y1","x2","y2"}')

    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    image = relationship("Image", back_populates="annotations")
    defect_class = relationship("DefectClass", back_populates="annotations")
