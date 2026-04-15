# -*- coding: utf-8 -*-
"""
应用配置
========
通过环境变量或 .env 文件加载配置。
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---- 数据库 ----
    DATABASE_URL: str = "mysql+pymysql://root:yolo26seg@localhost:3306/yolo_seg?charset=utf8mb4"

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/0"

    # ---- 文件存储 ----
    STORAGE_ROOT: str = str(Path(__file__).parent.parent / "storage")
    UPLOAD_DIR: str = "uploads"      # 相对于 STORAGE_ROOT
    DATASET_DIR: str = "datasets"
    RUNS_DIR: str = "runs"
    EXPORT_DIR: str = "exports"

    # ---- 服务 ----
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:80"]

    # ---- 图像 ----
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024   # 50MB
    THUMB_SIZE: int = 256                      # 缩略图最大边长

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def upload_path(self) -> Path:
        p = Path(self.STORAGE_ROOT).resolve() / self.UPLOAD_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def dataset_path(self) -> Path:
        p = Path(self.STORAGE_ROOT).resolve() / self.DATASET_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def runs_path(self) -> Path:
        p = Path(self.STORAGE_ROOT).resolve() / self.RUNS_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
