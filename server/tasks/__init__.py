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

broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL
broker_transport_options = {}

if broker_url.startswith("filesystem://"):
    broker_dir = Path(settings.CELERY_FILESYSTEM_BROKER_DIR)
    if not broker_dir.is_absolute():
        broker_dir = Path(settings.STORAGE_ROOT).resolve() / broker_dir
    queue_dir = broker_dir / "queue"
    processed_dir = broker_dir / "processed"
    for d in (queue_dir, processed_dir):
        d.mkdir(parents=True, exist_ok=True)
    broker_transport_options = {
        "data_folder_in": str(queue_dir),
        "data_folder_out": str(queue_dir),
        "processed_folder": str(processed_dir),
        "store_processed": True,
    }

celery_app = Celery(
    "yolo_seg",
    broker=broker_url,
    backend=result_backend or None,
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
    broker_transport_options=broker_transport_options,
)

# 显式导入任务模块（确保任务被注册）
from .train_task import run_training_pipeline  # noqa

# Celery CLI 需要名为 'celery' 的属性（-A server.tasks 会查找它）
celery = celery_app
