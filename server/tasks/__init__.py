# -*- coding: utf-8 -*-
"""
Celery 异步任务队列配置
"""

import sys
from pathlib import Path

# 将项目根目录加入 sys.path，确保 core/ 模块可被导入
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from celery import Celery
from ..config import settings

celery_app = Celery(
    "yolo_seg",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 训练任务可能跑几个小时，设置足够长的超时
    task_time_limit=86400,       # 24小时硬限制
    task_soft_time_limit=72000,  # 20小时软限制
    # 同一时间只跑一个训练任务（GPU 资源限制）
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
)

# 显式导入任务模块（确保任务被注册）
from .train_task import run_training_pipeline  # noqa

# Celery CLI 需要名为 'celery' 的属性（-A server.tasks 会查找它）
celery = celery_app
