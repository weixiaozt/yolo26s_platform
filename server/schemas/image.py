# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ImageOut(BaseModel):
    id: int
    project_id: int
    filename: str
    source_relative_path: Optional[str] = None
    width: int
    height: int
    file_size: int
    status: str
    annotator: Optional[str]
    reviewer: Optional[str]
    created_at: datetime
    annotation_count: int = 0
    class_id: Optional[int] = None  # cls 项目的图级分类 id
    model_config = {"from_attributes": True}


class ImageListOut(BaseModel):
    """分页图像列表"""
    total: int
    page: int
    page_size: int
    items: list[ImageOut]


class ImageUploadOut(BaseModel):
    """图片上传结果 + 自动按文件夹名标注报告"""
    items: list[ImageOut]
    uploaded: int = 0
    auto_labeled: int = 0
    renamed: list[dict] = Field(default_factory=list)
    unknown_folders: list[str] = Field(default_factory=list)
    matched_classes: dict[str, int] = Field(default_factory=dict)


class FolderLabelOut(BaseModel):
    """按 source_relative_path 的文件夹名批量打分类标签结果"""
    updated: int = 0
    skipped: int = 0
    unknown_folders: list[str] = Field(default_factory=list)
    matched_classes: dict[str, int] = Field(default_factory=dict)


class ImageStatusUpdate(BaseModel):
    status: str  # unlabeled / labeling / labeled / reviewed
    annotator: Optional[str] = None
    reviewer: Optional[str] = None
