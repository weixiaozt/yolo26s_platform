# -*- coding: utf-8 -*-
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from ..database import Base


class ExportedModel(Base):
    __tablename__ = "exported_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)  # 关联训练任务
    source_path = Column(String(500), nullable=False)       # 源 .pt 路径
    source_type = Column(String(10), default="best")        # best / last
    export_format = Column(String(20), nullable=False)       # onnx / openvino / tensorrt
    export_path = Column(String(500))                        # 导出文件/目录路径
    onnx_path = Column(String(500))                          # 中间 ONNX 路径
    file_size_mb = Column(Float, default=0)                  # 文件大小 MB
    imgsz = Column(Integer, default=640)
    half = Column(Integer, default=0)                        # 0=FP32, 1=FP16, 2=INT8
    nms = Column(Integer, default=0)                         # 0=不带 NMS, 1=内嵌 NMS（输出 1×300×6+nm）
    head_mode = Column(String(20), default="legacy")         # legacy / native / compat
    status = Column(String(20), default="pending")           # pending/exporting/completed/failed
    error_message = Column(String(2000))
    created_at = Column(DateTime, server_default=func.now())
