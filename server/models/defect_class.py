# -*- coding: utf-8 -*-
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class DefectClass(Base):
    __tablename__ = "defect_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    class_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="类别编号 0,1,2… 对应 YOLO 标签")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="类别名称")
    color: Mapped[str] = mapped_column(String(7), default="#FF0000", comment="前端显示颜色 hex")

    # 关系
    project = relationship("Project", back_populates="defect_classes")
    annotations = relationship("Annotation", back_populates="defect_class")
