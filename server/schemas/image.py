# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ImageOut(BaseModel):
    id: int
    project_id: int
    filename: str
    width: int
    height: int
    file_size: int
    status: str
    annotator: Optional[str]
    reviewer: Optional[str]
    created_at: datetime
    annotation_count: int = 0
    model_config = {"from_attributes": True}


class ImageListOut(BaseModel):
    """分页图像列表"""
    total: int
    page: int
    page_size: int
    items: list[ImageOut]


class ImageStatusUpdate(BaseModel):
    status: str  # unlabeled / labeling / labeled / reviewed
    annotator: Optional[str] = None
    reviewer: Optional[str] = None
