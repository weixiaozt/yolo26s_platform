# -*- coding: utf-8 -*-
"""
训练流水线 Celery 任务
======================
异步执行完整训练流水线：数据集构建 → 预处理 → 滑窗 → 划分 → 训练。
通过 epoch_callback 将训练指标实时写入 MySQL，前端通过轮询或 WebSocket 获取。
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中，以便导入 core/ 模块
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from . import celery_app
from ..database import SessionLocal
from ..models.train_task import TrainTask, TrainEpochLog
from ..services.dataset_service import prepare_full_dataset
from ..config import settings


@celery_app.task(bind=True, name="tasks.run_training_pipeline")
def run_training_pipeline(self, task_id: int):
    """
    Celery 异步任务：执行完整训练流水线。
    """
    # 确保 core/ 可导入（Windows Celery 环境下 sys.path 可能不含项目根目录）
    import sys
    _root = str(Path(__file__).parent.parent.parent)
    if _root not in sys.path:
        sys.path.insert(0, _root)

    db = SessionLocal()

    try:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        config = task.config or {}
        project_id = task.project_id

        # 更新状态
        task.status = "preparing"
        task.started_at = datetime.now()
        db.commit()

        # ---- 任务目录 ----
        task_dir = settings.runs_path / f"task_{task_id}"
        task_dir.mkdir(parents=True, exist_ok=True)
        task.output_dir = str(task_dir)
        db.commit()

        # ---- 阶段 1~3: 数据集准备 ----
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
            bg_keep_ratio=0,
            use_morphology=config.get("use_morphology", True),
            dilate_kernel=config.get("dilate_kernel", 3),
            erode_kernel=config.get("erode_kernel", 3),
            mask_dilate_kernel=config.get("mask_dilate_kernel", 0),
        )

        dataset_dir = dataset_result["dataset_dir"]
        class_names = dataset_result["class_names"]

        # 保存类别信息到 config（供后续继承训练时校验）
        config["class_names"] = class_names
        task.config = config
        db.commit()

        # ---- 生成 dataset.yaml ----
        from core.train import generate_dataset_yaml
        dataset_yaml = str(task_dir / "dataset.yaml")
        generate_dataset_yaml(
            dataset_dir=dataset_dir,
            output_path=dataset_yaml,
            class_names=class_names,
        )

        # ---- 阶段 4: 模型训练 ----
        task.status = "training"
        task.epochs = config.get("epochs", 150)
        db.commit()

        # 确定模型来源（从头训练 or 继承训练）
        model_name = config.get("model_name", "yolo26s-seg")  # 用户选择的模型尺寸
        train_mode = config.get("train_mode", "scratch")
        if train_mode == "finetune":
            resume_task_id = config.get("resume_from_task_id")
            resume_model_type = config.get("resume_model_type", "best")
            if resume_task_id:
                prev_task = db.query(TrainTask).filter(TrainTask.id == resume_task_id).first()
                if prev_task:
                    prev_path = prev_task.best_model_path if resume_model_type == "best" else prev_task.last_model_path
                    if prev_path and Path(prev_path).exists():
                        model_name = prev_path
                        print(f"[继承训练] 从 Task#{resume_task_id} {resume_model_type}.pt 继续: {prev_path}")
                    else:
                        print(f"[警告] 继承模型不存在，回退为从头训练")
                else:
                    print(f"[警告] 找不到 Task#{resume_task_id}，回退为从头训练")

        def cancel_check() -> bool:
            """
            被 core/train.py 周期性调用，检查训练任务是否需要中止。
            判定条件：
              - 任务记录已被删除（用户在前端误删了正在跑的任务）
              - 任务状态被改成 'cancelled'（用户在前端按了取消/暂停）
            返回 True 时，Ultralytics 会在最近的 epoch 边界停止训练。
            用独立 session 查询，避免与外层 db 的事务隔离冲突。
            """
            check_db = SessionLocal()
            try:
                t = check_db.query(TrainTask).filter(TrainTask.id == task_id).first()
                if t is None:
                    return True  # 任务被删除
                if t.status == "cancelled":
                    return True
                return False
            except Exception as e:
                print(f"[cancel_check db error] {e}")
                return False
            finally:
                check_db.close()

        def epoch_callback(data: dict):
            """
            每个 epoch 结束后的回调。
            写入 train_epoch_logs 表，更新 train_tasks 进度。
            """
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

                # 更新任务进度
                task_obj = db.query(TrainTask).filter(TrainTask.id == task_id).first()
                if task_obj:
                    task_obj.current_epoch = data.get("epoch", 0) + 1
                    map50 = data.get("mAP50_B", 0)
                    if task_obj.best_map50 is None or map50 > task_obj.best_map50:
                        task_obj.best_map50 = map50

                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[epoch_callback error] {e}")

        # 调用现有 core/train.py
        from core.train import run_train
        train_result = run_train(
            dataset_yaml=dataset_yaml,
            output_dir=str(task_dir / "runs"),
            model_name=model_name,
            imgsz=config.get("crop_size", 640),
            epochs=config.get("epochs", 150),
            batch_size=config.get("batch_size", 16),
            patience=config.get("patience", 0),
            device=config.get("device", "0"),
            augment_hsv_h=config.get("hsv_h", 0.015),
            augment_hsv_s=config.get("hsv_s", 0.7),
            augment_hsv_v=config.get("hsv_v", 0.4),
            augment_degrees=config.get("degrees", 10.0),
            augment_translate=config.get("translate", 0.1),
            augment_scale=config.get("scale", 0.5),
            augment_shear=config.get("shear", 5.0),
            augment_flipud=config.get("flipud", 0.5),
            augment_fliplr=config.get("fliplr", 0.5),
            augment_mosaic=config.get("mosaic", 0.3),
            augment_mixup=config.get("mixup", 0.1),
            augment_copy_paste=config.get("copy_paste", 0.5),
            augment_erasing=config.get("erasing", 0.0),
            close_mosaic=config.get("close_mosaic", 30),
            lr0=config.get("lr0", 0.01),
            lrf=config.get("lrf", 0.01),
            momentum=config.get("momentum", 0.937),
            weight_decay=config.get("weight_decay", 0.0005),
            warmup_epochs=config.get("warmup_epochs", 3.0),
            warmup_momentum=config.get("warmup_momentum", 0.8),
            epoch_callback=epoch_callback,
            cancel_check=cancel_check,
        )

        # ---- 训练完成或被取消 ----
        # 重新查一次任务状态：
        #   - 若任务已被前端取消，状态已是 'cancelled'，不要覆盖回 completed
        #   - 若任务记录被删除，直接退出，不写任何东西
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task is None:
            print(f"[训练任务] Task#{task_id} 已被删除，跳过完成态写入")
            return {"status": "cancelled (deleted)"}

        if task.status == "cancelled":
            # 已被取消，记录最后产出的模型路径但保持 cancelled 状态
            task.best_model_path = train_result.get("best_pt")
            task.last_model_path = train_result.get("last_pt")
            task.finished_at = datetime.now()
            db.commit()
            return {"status": "cancelled", "best_pt": train_result.get("best_pt")}

        task.status = "completed"
        task.best_model_path = train_result.get("best_pt")
        task.last_model_path = train_result.get("last_pt")
        task.finished_at = datetime.now()
        db.commit()

        return {
            "status": "completed",
            "best_pt": train_result.get("best_pt"),
            "last_pt": train_result.get("last_pt"),
        }

    except Exception as e:
        task = db.query(TrainTask).filter(TrainTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = f"{str(e)}\n{traceback.format_exc()}"
            task.finished_at = datetime.now()
            db.commit()
        return {"status": "failed", "error": str(e)}

    finally:
        db.close()
