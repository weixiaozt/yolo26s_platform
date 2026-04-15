# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---- DefectClass ----
class DefectClassCreate(BaseModel):
    class_index: int = Field(ge=0, description="类别编号 0,1,2…")
    name: str = Field(max_length=100)
    color: str = Field(default="#FF0000", max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$")


class DefectClassOut(DefectClassCreate):
    id: int
    model_config = {"from_attributes": True}


# ---- Project ----
class ProjectCreate(BaseModel):
    name: str = Field(max_length=200)
    description: Optional[str] = None
    resize_h: int = Field(default=2048, ge=640)
    resize_w: int = Field(default=2048, ge=640)
    crop_size: int = Field(default=640, ge=320, le=8192)
    overlap: float = Field(default=0.2, ge=0.0, le=0.5)
    class_names: list[DefectClassCreate] = Field(
        default_factory=lambda: [
            DefectClassCreate(class_index=0, name="defect_1", color="#FF0000"),
            DefectClassCreate(class_index=1, name="defect_2", color="#00FF00"),
            DefectClassCreate(class_index=2, name="defect_3", color="#0000FF"),
        ]
    )


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    resize_h: Optional[int] = None
    resize_w: Optional[int] = None
    crop_size: Optional[int] = None
    overlap: Optional[float] = None
    status: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    resize_h: int
    resize_w: int
    crop_size: int
    overlap: float
    status: str
    created_at: datetime
    updated_at: datetime
    defect_classes: list[DefectClassOut] = []
    model_config = {"from_attributes": True}


class ProjectStats(ProjectOut):
    """带统计信息的项目详情"""
    total_images: int = 0
    unlabeled_count: int = 0
    labeling_count: int = 0
    labeled_count: int = 0
    reviewed_count: int = 0
    total_annotations: int = 0
