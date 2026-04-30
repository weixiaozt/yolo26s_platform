# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TrainConfig(BaseModel):
    """训练参数配置（硅片缺陷检测优化预设）"""
    # 训练模式
    train_mode: str = Field(default="scratch", description="scratch=从头训练, finetune=继承训练")
    resume_from_task_id: Optional[int] = Field(default=None, description="继承训练时，从哪个任务的模型开始")
    resume_model_type: str = Field(default="best", description="继承的模型类型: best/last")

    # 模型选择
    model_name: str = Field(default="yolo26s-seg", description="模型尺寸: yolo26n/s/m/l/x-seg")

    # 数据划分
    train_ratio: float = Field(default=0.8, ge=0.5, le=0.95)
    oversample_factor: int = Field(default=5, ge=1, le=20)

    # 基本训练
    epochs: int = Field(default=200, ge=1, le=2000)
    batch_size: int = Field(default=16, ge=1, le=128)
    patience: int = Field(default=50, ge=0)
    device: str = Field(default="0")

    # 学习率
    lr0: float = Field(default=0.01)
    lrf: float = Field(default=0.01)
    momentum: float = Field(default=0.937)
    weight_decay: float = Field(default=0.0005)
    warmup_epochs: float = Field(default=3.0)
    warmup_momentum: float = Field(default=0.8)

    # 颜色增广
    hsv_h: float = 0.015
    hsv_s: float = 0.7
    hsv_v: float = 0.4

    # 几何增广
    degrees: float = 180.0
    translate: float = 0.1
    scale: float = 0.5
    shear: float = 0.0
    flipud: float = 0.5
    fliplr: float = 0.5

    # 高级增广
    mosaic: float = 0.5
    mixup: float = 0.1
    copy_paste: float = 0.5
    erasing: float = 0.1
    close_mosaic: int = 30

    # 形态学预处理
    use_morphology: bool = True
    dilate_kernel: int = Field(default=3, ge=1, le=15)
    erode_kernel: int = Field(default=3, ge=1, le=15)
    mask_dilate_kernel: int = Field(default=0, ge=0, le=15)


class TrainTaskCreate(BaseModel):
    task_name: str = Field(max_length=200)
    config: TrainConfig = Field(default_factory=TrainConfig)


class TrainTaskOut(BaseModel):
    id: int
    project_id: int
    task_name: str
    status: str
    epochs: int
    current_epoch: int
    best_map50: Optional[float]
    best_fitness: Optional[float] = None
    best_model_path: Optional[str]
    last_model_path: Optional[str]
    output_dir: Optional[str]
    error_message: Optional[str]
    config: Optional[dict] = None
    num_classes: Optional[int] = None
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    model_config = {"from_attributes": True}


class EpochLogOut(BaseModel):
    epoch: int
    train_box_loss: Optional[float]
    train_seg_loss: Optional[float]
    train_cls_loss: Optional[float]
    train_dfl_loss: Optional[float]
    val_box_loss: Optional[float]
    val_seg_loss: Optional[float]
    val_cls_loss: Optional[float]
    val_dfl_loss: Optional[float]
    precision_b: Optional[float]
    recall_b: Optional[float]
    map50_b: Optional[float]
    map50_95_b: Optional[float]
    map50_m: Optional[float]
    map50_95_m: Optional[float]
    lr: Optional[float]
    model_config = {"from_attributes": True}
