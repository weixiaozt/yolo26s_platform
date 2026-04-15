# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PointSchema(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class AnnotationCreate(BaseModel):
    class_id: int
    polygon: list[PointSchema] = Field(min_length=3, description="至少3个点构成多边形")
    area: Optional[float] = None
    bbox: Optional[dict] = None
    created_by: Optional[str] = None


class AnnotationOut(BaseModel):
    id: int
    image_id: int
    class_id: int
    polygon: list[dict]
    area: Optional[float]
    bbox: Optional[dict]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    # 关联的类别信息
    class_name: Optional[str] = None
    class_color: Optional[str] = None
    model_config = {"from_attributes": True}


class AnnotationBatchSave(BaseModel):
    """
    全量覆盖保存：前端一次提交某张图的所有标注。
    后端先删除该图所有旧标注，再批量插入新标注。
    """
    annotations: list[AnnotationCreate]
    annotator: Optional[str] = None
