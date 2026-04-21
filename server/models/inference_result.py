# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON
from sqlalchemy.sql import func
from ..database import Base


class InferenceResult(Base):
    __tablename__ = "inference_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, nullable=False, index=True)
    task_id = Column(Integer, nullable=False)  # 使用的训练任务ID
    model_type = Column(String(10), default="best")  # best / last
    filename = Column(String(500), nullable=False)
    device = Column(String(20), default="cpu")
    conf_thresh = Column(Float, default=0.15)
    iou_thresh = Column(Float, default=0.5)
    resize_size = Column(Integer, default=0)

    # 结果
    num_detections = Column(Integer, default=0)
    inference_time = Column(Float, default=0)
    detections = Column(JSON, default=list)  # [{class_id, confidence, bbox}]

    # 图像路径（存磁盘，不存base64）
    original_path = Column(String(500))
    overlay_path = Column(String(500))
    overlay_morph_path = Column(String(500))  # 形态学三通道叠加图
    mask_path = Column(String(500))

    created_at = Column(DateTime, server_default=func.now())
