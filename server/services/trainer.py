# -*- coding: utf-8 -*-
"""
后台训练服务（使用线程，无需 Redis/Celery）
=============================================
单用户场景下，直接用 Python 线程在后台执行训练任务。
同一时间只允许一个训练任务运行（GPU 资源限制）。
"""

import threading
import traceback
from datetime import datetime
from pathlib import Path

from ..database import SessionLocal
from ..models.train_task import TrainTask, TrainEpochLog
from ..services.dataset_service import prepare_full_dataset
from ..config import settings


class BackgroundTrainer:
    """后台训练管理器（单例）"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._current_task_id: int | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_task_id(self) -> int | None:
        return self._current_task_id if self.is_running else None

    def start(self, task_id: int):
        with self._lock:
            if self.is_running:
                raise RuntimeError(f"训练任务 {self._current_task_id} 正在运行中，请等待完成")
            self._current_task_id = task_id
            self._thread = threading.Thread(
                target=self._run_pipeline,
                args=(task_id,),
                daemon=True,
            )
            self._thread.start()

    def _run_pipeline(self, task_id: int):
        """在后台线程中执行完整训练流水线"""
        db = SessionLocal()
        try:
            task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
            if not task:
                return

            config = task.config or {}
            project_id = task.project_id

            # 更新状态
            task.status = "preparing"
            task.started_at = datetime.now()
            task_dir = settings.runs_path / f"task_{task_id}"
            task_dir.mkdir(parents=True, exist_ok=True)
            task.output_dir = str(task_dir)
            db.commit()

            # ---- 数据集准备 ----
            dataset_result = prepare_full_dataset(
                project_id=project_id,
                task_output_dir=str(task_dir),
                db=db,
                target_h=config.get("resize_h", 2048),
                target_w=config.get("resize_w", 2048),
                crop_size=config.get("crop_size", 640),
                overlap=config.get("overlap", 0.2),
                train_ratio=config.get("train_ratio", 0.8),
                oversample_factor=config.get("oversample_factor", 5),
                bg_keep_ratio=0,  # 未标注图不参与训练
            )
            dataset_dir = dataset_result["dataset_dir"]
            class_names = dataset_result["class_names"]

            # ---- 生成 dataset.yaml ----
            from core.train import generate_dataset_yaml
            dataset_yaml = str(task_dir / "dataset.yaml")
            generate_dataset_yaml(
                dataset_dir=dataset_dir,
                output_path=dataset_yaml,
                class_names=class_names,
            )

            # ---- 训练 ----
            task.status = "training"
            task.epochs = config.get("epochs", 200)
            db.commit()

            def epoch_callback(data: dict):
                try:
                    epoch_log = TrainEpochLog(
                        task_id=task_id,
                        epoch=data.get("epoch", 0),
                        train_box_loss=data.get("train_box_loss"),
                        train_seg_loss=data.get("train_seg_loss"),
                        train_cls_loss=data.get("train_cls_loss"),
                        train_dfl_loss=data.get("train_dfl_loss"),
                        val_box_loss=data.get("val_box_loss"),
                        val_seg_loss=data.get("val_seg_loss"),
                        val_cls_loss=data.get("val_cls_loss"),
                        val_dfl_loss=data.get("val_dfl_loss"),
                        precision_b=data.get("precision_B"),
                        recall_b=data.get("recall_B"),
                        map50_b=data.get("mAP50_B"),
                        map50_95_b=data.get("mAP50_95_B"),
                        map50_m=data.get("mAP50_M"),
                        map50_95_m=data.get("mAP50_95_M"),
                        lr=data.get("lr"),
                    )
                    db.add(epoch_log)
                    t = db.query(TrainTask).filter(TrainTask.id == task_id).first()
                    if t:
                        t.current_epoch = data.get("epoch", 0) + 1
                        m50 = data.get("mAP50_B", 0)
                        if t.best_map50 is None or m50 > t.best_map50:
                            t.best_map50 = m50
                    db.commit()
                except Exception as e:
                    db.rollback()
                    print(f"[epoch_callback error] {e}")

            from core.train import run_train
            train_result = run_train(
                dataset_yaml=dataset_yaml,
                output_dir=str(task_dir / "runs"),
                imgsz=config.get("crop_size", 640),
                epochs=config.get("epochs", 200),
                batch_size=config.get("batch_size", 8),
                patience=config.get("patience", 50),
                device=config.get("device", "0"),
                augment_hsv_h=config.get("hsv_h", 0.015),
                augment_hsv_s=config.get("hsv_s", 0.7),
                augment_hsv_v=config.get("hsv_v", 0.4),
                augment_degrees=config.get("degrees", 180.0),
                augment_translate=config.get("translate", 0.1),
                augment_scale=config.get("scale", 0.5),
                augment_shear=config.get("shear", 0.0),
                augment_flipud=config.get("flipud", 0.5),
                augment_fliplr=config.get("fliplr", 0.5),
                augment_mosaic=config.get("mosaic", 0.5),
                augment_mixup=config.get("mixup", 0.1),
                augment_copy_paste=config.get("copy_paste", 0.5),
                augment_erasing=config.get("erasing", 0.1),
                close_mosaic=config.get("close_mosaic", 30),
                lr0=config.get("lr0", 0.01),
                lrf=config.get("lrf", 0.01),
                momentum=config.get("momentum", 0.937),
                weight_decay=config.get("weight_decay", 0.0005),
                warmup_epochs=config.get("warmup_epochs", 3.0),
                warmup_momentum=config.get("warmup_momentum", 0.8),
                epoch_callback=epoch_callback,
            )

            task.status = "completed"
            task.best_model_path = train_result.get("best_pt")
            task.last_model_path = train_result.get("last_pt")
            task.finished_at = datetime.now()
            db.commit()

        except Exception as e:
            task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.error_message = f"{str(e)}\n{traceback.format_exc()}"
                task.finished_at = datetime.now()
                db.commit()
        finally:
            db.close()
            with self._lock:
                self._current_task_id = None


# 全局单例
trainer = BackgroundTrainer()
