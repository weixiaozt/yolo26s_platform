# -*- coding: utf-8 -*-
"""
项目整包导入导出
================
- 导出：将项目元数据、类别、已标注图片、标注多边形打包成 ZIP
- 导入：解析 ZIP 文件，创建新项目并恢复所有数据

ZIP 结构:
    project_export.zip
    ├── project.json         项目配置 + 类别定义
    ├── images.json          图片元数据列表
    ├── annotations.json     标注数据列表
    └── images/              原图文件
        └── {filename}
"""

import hashlib
import json
import shutil
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models.project import Project
from ..models.defect_class import DefectClass
from ..models.image import Image
from ..models.annotation import Annotation
from ..models.train_task import TrainTask, TrainEpochLog

# 单个 ZIP 内文件解压后大小上限（防 zip bomb），200MB 远超任何真实工业图
_MAX_ENTRY_SIZE = 200 * 1024 * 1024
_MAX_WEIGHT_SIZE = 2 * 1024 * 1024 * 1024
_VALID_TASK_TYPES = {"seg", "det", "cls", "obb"}
_VALID_PROJECT_STATUSES = {"active", "archived"}
_VALID_IMAGE_STATUSES = {"unlabeled", "labeling", "labeled", "reviewed"}
_VALID_TASK_STATUSES = {"pending", "preparing", "training", "exporting", "completed", "failed", "cancelled"}


def _sha256_file(path: Path) -> str | None:
    """流式计算文件 sha256（大图也不爆内存）。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def export_project_to_zip(project_id: int, db: Session, out_path: Path) -> dict:
    """将项目导出为 ZIP 文件，仅导出已标注的图片及其标注。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"项目 {project_id} 不存在")

    defect_classes = (
        db.query(DefectClass)
        .filter(DefectClass.project_id == project_id)
        .order_by(DefectClass.class_index)
        .all()
    )
    class_id_to_index = {dc.id: dc.class_index for dc in defect_classes}

    # 只导出已标注或已审核的图片
    images = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.status.in_(["labeled", "reviewed"]))
        .all()
    )

    project_data = {
        "name": project.name,
        "description": project.description,
        "task_type": project.task_type,
        "resize_h": project.resize_h,
        "resize_w": project.resize_w,
        "crop_size": project.crop_size,
        "overlap": project.overlap,
        "defect_classes": [
            {"class_index": dc.class_index, "name": dc.name, "color": dc.color}
            for dc in defect_classes
        ],
        "exported_at": datetime.now().isoformat(),
        "source_project_id": project_id,
    }
    images_data = []
    annotations_data = []
    upload_root = settings.upload_path
    missing_files = []

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for img in images:
            src_path = upload_root / img.file_path
            if not src_path.exists():
                missing_files.append(img.file_path)
                continue

            # ZIP 内文件名使用 file_path 的 basename（已含 uuid 前缀，保证唯一）
            zip_img_name = Path(img.file_path).name

            # 内容哈希：优先用 DB 列；存量未 backfill 的现场流式计算（合并标注集时按它匹配同一张图）
            content_hash = img.content_hash or _sha256_file(src_path)

            # cls 图级标签：用 class_index（跨项目可移植）；非 cls 留空
            images_data.append({
                "zip_filename": zip_img_name,
                "original_filename": img.filename,
                "source_relative_path": img.source_relative_path,
                "width": img.width,
                "height": img.height,
                "status": img.status,
                "annotator": img.annotator,
                "reviewer": img.reviewer,
                "class_index": class_id_to_index.get(img.class_id) if img.class_id else None,
                "content_hash": content_hash,
            })

            zf.write(str(src_path), f"images/{zip_img_name}")

            # 收集该图片的所有标注
            for ann in img.annotations:
                ci = class_id_to_index.get(ann.class_id)
                if ci is None:
                    continue
                annotations_data.append({
                    "image_zip_filename": zip_img_name,
                    "class_index": ci,
                    "polygon": ann.polygon,
                    "area": ann.area,
                    "bbox": ann.bbox,
                    "created_by": ann.created_by,
                })

        zf.writestr("project.json", json.dumps(project_data, ensure_ascii=False, indent=2))
        zf.writestr("images.json", json.dumps(images_data, ensure_ascii=False, indent=2))
        zf.writestr("annotations.json", json.dumps(annotations_data, ensure_ascii=False, indent=2))

    return {
        "image_count": len(images_data),
        "annotation_count": len(annotations_data),
        "missing_files": missing_files,
        "zip_size": out_path.stat().st_size,
    }


def export_full_project_to_zip(project_id: int, db: Session, out_path: Path) -> dict:
    """导出完整项目迁移包。

    包含全部项目图片、标注、项目配置、训练任务记录、epoch 日志，以及存在的
    best.pt / last.pt。刻意不导出训练生成的 dataset/、推理结果和导出模型，
    这些要么可重建，要么体积过大。
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"项目 {project_id} 不存在")

    defect_classes = (
        db.query(DefectClass)
        .filter(DefectClass.project_id == project_id)
        .order_by(DefectClass.class_index)
        .all()
    )
    class_id_to_index = {dc.id: dc.class_index for dc in defect_classes}
    images = db.query(Image).filter(Image.project_id == project_id).order_by(Image.id).all()
    tasks = db.query(TrainTask).filter(TrainTask.project_id == project_id).order_by(TrainTask.id).all()

    project_data = {
        "name": project.name,
        "description": project.description,
        "task_type": project.task_type,
        "resize_h": project.resize_h,
        "resize_w": project.resize_w,
        "crop_size": project.crop_size,
        "overlap": project.overlap,
        "status": project.status,
        "last_train_config": project.last_train_config,
        "defect_classes": [
            {"class_index": dc.class_index, "name": dc.name, "color": dc.color}
            for dc in defect_classes
        ],
        "exported_at": datetime.now().isoformat(),
        "source_project_id": project_id,
    }
    manifest = {
        "package_type": "full_project",
        "version": 1,
        "created_at": datetime.now().isoformat(),
    }

    images_data = []
    annotations_data = []
    train_tasks_data = []
    epoch_logs_data = []
    missing_files = []
    exported_weights = 0
    upload_root = settings.upload_path

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for img in images:
            src_path = upload_root / img.file_path
            if not src_path.exists():
                missing_files.append(img.file_path)
                continue

            zip_img_name = Path(img.file_path).name
            content_hash = img.content_hash or _sha256_file(src_path)
            images_data.append({
                "old_id": img.id,
                "zip_filename": zip_img_name,
                "original_filename": img.filename,
                "source_relative_path": img.source_relative_path,
                "width": img.width,
                "height": img.height,
                "file_size": img.file_size,
                "status": img.status,
                "annotator": img.annotator,
                "reviewer": img.reviewer,
                "class_index": class_id_to_index.get(img.class_id) if img.class_id else None,
                "content_hash": content_hash,
                "created_at": img.created_at.isoformat() if img.created_at else None,
            })
            zf.write(str(src_path), f"images/{zip_img_name}")

            for ann in img.annotations:
                ci = class_id_to_index.get(ann.class_id)
                if ci is None:
                    continue
                annotations_data.append({
                    "old_id": ann.id,
                    "image_old_id": img.id,
                    "image_zip_filename": zip_img_name,
                    "class_index": ci,
                    "polygon": ann.polygon,
                    "area": ann.area,
                    "bbox": ann.bbox,
                    "created_by": ann.created_by,
                    "created_at": ann.created_at.isoformat() if ann.created_at else None,
                    "updated_at": ann.updated_at.isoformat() if ann.updated_at else None,
                })

        for task in tasks:
            weight_files = {}
            for key, path_str in (("best", task.best_model_path), ("last", task.last_model_path)):
                if not path_str:
                    continue
                p = Path(path_str)
                if not p.exists() or not p.is_file():
                    continue
                arc = f"weights/task_{task.id}/{key}.pt"
                try:
                    zf.write(str(p), arc)
                except OSError:
                    missing_files.append(path_str)
                    continue
                weight_files[key] = arc
                exported_weights += 1

            train_tasks_data.append({
                "old_id": task.id,
                "task_name": task.task_name,
                "status": task.status,
                "config": task.config,
                "epochs": task.epochs,
                "current_epoch": task.current_epoch,
                "best_map50": task.best_map50,
                "best_fitness": task.best_fitness,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "finished_at": task.finished_at.isoformat() if task.finished_at else None,
                "weights": weight_files,
            })

            for log in task.epoch_logs:
                epoch_logs_data.append({
                    "task_old_id": task.id,
                    "epoch": log.epoch,
                    "train_box_loss": log.train_box_loss,
                    "train_seg_loss": log.train_seg_loss,
                    "train_cls_loss": log.train_cls_loss,
                    "train_dfl_loss": log.train_dfl_loss,
                    "val_box_loss": log.val_box_loss,
                    "val_seg_loss": log.val_seg_loss,
                    "val_cls_loss": log.val_cls_loss,
                    "val_dfl_loss": log.val_dfl_loss,
                    "precision_b": log.precision_b,
                    "recall_b": log.recall_b,
                    "map50_b": log.map50_b,
                    "map50_95_b": log.map50_95_b,
                    "map50_m": log.map50_m,
                    "map50_95_m": log.map50_95_m,
                    "top1_acc": log.top1_acc,
                    "top5_acc": log.top5_acc,
                    "lr": log.lr,
                })

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("project.json", json.dumps(project_data, ensure_ascii=False, indent=2))
        zf.writestr("images.json", json.dumps(images_data, ensure_ascii=False, indent=2))
        zf.writestr("annotations.json", json.dumps(annotations_data, ensure_ascii=False, indent=2))
        zf.writestr("train_tasks.json", json.dumps(train_tasks_data, ensure_ascii=False, indent=2))
        zf.writestr("epoch_logs.json", json.dumps(epoch_logs_data, ensure_ascii=False, indent=2))

    return {
        "image_count": len(images_data),
        "annotation_count": len(annotations_data),
        "train_task_count": len(train_tasks_data),
        "weight_file_count": exported_weights,
        "missing_files": missing_files,
        "zip_size": out_path.stat().st_size,
    }


def _resolve_project_name(db: Session, base_name: str) -> str:
    """项目重名时自动加后缀。"""
    existing = {p.name for p in db.query(Project.name).all()}
    if base_name not in existing:
        return base_name
    suffix = datetime.now().strftime("%Y%m%d")
    candidate = f"{base_name}_{suffix}"
    if candidate not in existing:
        return candidate
    i = 2
    while f"{candidate}_{i}" in existing:
        i += 1
    return f"{candidate}_{i}"


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def import_full_project_from_zip(zip_file: BinaryIO, db: Session) -> dict:
    """从完整项目迁移包导入新项目。"""
    with zipfile.ZipFile(zip_file) as zf:
        required = {
            "manifest.json", "project.json", "images.json", "annotations.json",
            "train_tasks.json", "epoch_logs.json",
        }
        names = set(zf.namelist())
        if not required.issubset(names):
            missing = required - names
            raise ValueError(f"ZIP 缺少完整项目包必要文件: {missing}")

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("package_type") != "full_project":
            raise ValueError("这不是完整项目包，请使用“导出项目”生成的 ZIP")

        project_data = json.loads(zf.read("project.json").decode("utf-8"))
        images_data = json.loads(zf.read("images.json").decode("utf-8"))
        annotations_data = json.loads(zf.read("annotations.json").decode("utf-8"))
        train_tasks_data = json.loads(zf.read("train_tasks.json").decode("utf-8"))
        epoch_logs_data = json.loads(zf.read("epoch_logs.json").decode("utf-8"))

        final_name = _resolve_project_name(db, project_data["name"])
        project = Project(
            name=final_name,
            description=project_data.get("description"),
            task_type=project_data.get("task_type") if project_data.get("task_type") in _VALID_TASK_TYPES else "seg",
            resize_h=project_data.get("resize_h", 2048),
            resize_w=project_data.get("resize_w", 2048),
            crop_size=project_data.get("crop_size", 640),
            overlap=project_data.get("overlap", 0.2),
            status=project_data.get("status") if project_data.get("status") in _VALID_PROJECT_STATUSES else "active",
            last_train_config=project_data.get("last_train_config"),
        )
        db.add(project)
        db.flush()

        class_index_to_id: dict[int, int] = {}
        for cls in project_data.get("defect_classes", []):
            dc = DefectClass(
                project_id=project.id,
                class_index=cls["class_index"],
                name=cls["name"],
                color=cls.get("color", "#FF0000"),
            )
            db.add(dc)
            db.flush()
            class_index_to_id[dc.class_index] = dc.id

        upload_dir = settings.upload_path / str(project.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_dir_resolved = upload_dir.resolve()

        old_image_id_to_new_id: dict[int, int] = {}
        zip_name_to_image_id: dict[str, int] = {}
        imported_images = 0
        for img_info in images_data:
            zip_name = img_info.get("zip_filename")
            safe_name = Path(zip_name or "").name
            if not safe_name or safe_name in (".", ".."):
                continue
            zip_path_in_archive = f"images/{safe_name}"
            if zip_path_in_archive not in names:
                continue
            try:
                info = zf.getinfo(zip_path_in_archive)
                if info.file_size > _MAX_ENTRY_SIZE:
                    continue
            except KeyError:
                continue

            new_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            target_path = upload_dir / new_name
            if not target_path.resolve().is_relative_to(upload_dir_resolved):
                continue
            with zf.open(zip_path_in_archive) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            cls_idx = img_info.get("class_index")
            image = Image(
                project_id=project.id,
                filename=img_info.get("original_filename", safe_name),
                source_relative_path=img_info.get("source_relative_path"),
                file_path=f"{project.id}/{new_name}",
                width=img_info.get("width", 0),
                height=img_info.get("height", 0),
                file_size=target_path.stat().st_size,
                status=img_info.get("status") if img_info.get("status") in _VALID_IMAGE_STATUSES else "unlabeled",
                annotator=img_info.get("annotator"),
                reviewer=img_info.get("reviewer"),
                class_id=class_index_to_id.get(cls_idx) if cls_idx is not None else None,
                content_hash=img_info.get("content_hash") or _sha256_file(target_path),
                created_at=_parse_dt(img_info.get("created_at")) or datetime.now(),
            )
            db.add(image)
            db.flush()
            if img_info.get("old_id") is not None:
                old_image_id_to_new_id[int(img_info["old_id"])] = image.id
            zip_name_to_image_id[safe_name] = image.id
            imported_images += 1

        imported_anns = 0
        for ann in annotations_data:
            img_id = None
            if ann.get("image_old_id") is not None:
                img_id = old_image_id_to_new_id.get(int(ann["image_old_id"]))
            if img_id is None:
                img_id = zip_name_to_image_id.get(Path(ann.get("image_zip_filename", "")).name)
            cls_id = class_index_to_id.get(ann.get("class_index"))
            if img_id is None or cls_id is None:
                continue
            a = Annotation(
                image_id=img_id,
                class_id=cls_id,
                polygon=ann["polygon"],
                area=ann.get("area"),
                bbox=ann.get("bbox"),
                created_by=ann.get("created_by"),
                created_at=_parse_dt(ann.get("created_at")) or datetime.now(),
                updated_at=_parse_dt(ann.get("updated_at")) or datetime.now(),
            )
            db.add(a)
            imported_anns += 1

        old_task_id_to_new_id: dict[int, int] = {}
        imported_tasks = 0
        imported_weights = 0
        active_states = {"pending", "preparing", "training", "exporting"}
        for task_info in train_tasks_data:
            old_status = task_info.get("status", "completed")
            if old_status not in _VALID_TASK_STATUSES:
                old_status = "completed"
            status = "cancelled" if old_status in active_states else old_status
            task = TrainTask(
                project_id=project.id,
                task_name=task_info.get("task_name", "导入训练任务"),
                status=status,
                celery_task_id=None,
                config=task_info.get("config"),
                epochs=task_info.get("epochs", 0),
                current_epoch=task_info.get("current_epoch", 0),
                best_map50=task_info.get("best_map50"),
                best_fitness=task_info.get("best_fitness"),
                error_message=task_info.get("error_message"),
                created_at=_parse_dt(task_info.get("created_at")) or datetime.now(),
                started_at=_parse_dt(task_info.get("started_at")),
                finished_at=_parse_dt(task_info.get("finished_at")),
            )
            if old_status in active_states:
                task.error_message = (task.error_message or "") + "\n[导入提示] 原任务导出时仍处于活跃状态，导入后标记为 cancelled。"
                task.finished_at = task.finished_at or datetime.now()
            db.add(task)
            db.flush()
            imported_tasks += 1
            if task_info.get("old_id") is not None:
                old_task_id_to_new_id[int(task_info["old_id"])] = task.id

            run_dir = settings.runs_path / f"task_{task.id}"
            weights_dir = run_dir / "runs" / "train" / "weights"
            weights_dir.mkdir(parents=True, exist_ok=True)
            task.output_dir = str(run_dir)

            weights = task_info.get("weights") or {}
            for key, arc in (("best", weights.get("best")), ("last", weights.get("last"))):
                if not arc or arc not in names:
                    continue
                try:
                    info = zf.getinfo(arc)
                    if info.file_size > _MAX_WEIGHT_SIZE:
                        continue
                except KeyError:
                    continue
                target = weights_dir / f"{key}.pt"
                with zf.open(arc) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if key == "best":
                    task.best_model_path = str(target)
                else:
                    task.last_model_path = str(target)
                imported_weights += 1

        imported_logs = 0
        for log_info in epoch_logs_data:
            old_task_id = log_info.get("task_old_id")
            if old_task_id is None:
                continue
            task_id = old_task_id_to_new_id.get(int(old_task_id))
            if task_id is None:
                continue
            db.add(TrainEpochLog(
                task_id=task_id,
                epoch=log_info.get("epoch", 0),
                train_box_loss=log_info.get("train_box_loss"),
                train_seg_loss=log_info.get("train_seg_loss"),
                train_cls_loss=log_info.get("train_cls_loss"),
                train_dfl_loss=log_info.get("train_dfl_loss"),
                val_box_loss=log_info.get("val_box_loss"),
                val_seg_loss=log_info.get("val_seg_loss"),
                val_cls_loss=log_info.get("val_cls_loss"),
                val_dfl_loss=log_info.get("val_dfl_loss"),
                precision_b=log_info.get("precision_b"),
                recall_b=log_info.get("recall_b"),
                map50_b=log_info.get("map50_b"),
                map50_95_b=log_info.get("map50_95_b"),
                map50_m=log_info.get("map50_m"),
                map50_95_m=log_info.get("map50_95_m"),
                top1_acc=log_info.get("top1_acc"),
                top5_acc=log_info.get("top5_acc"),
                lr=log_info.get("lr"),
            ))
            imported_logs += 1

        db.commit()
        return {
            "project_id": project.id,
            "project_name": final_name,
            "renamed": final_name != project_data["name"],
            "image_count": imported_images,
            "annotation_count": imported_anns,
            "train_task_count": imported_tasks,
            "epoch_log_count": imported_logs,
            "weight_file_count": imported_weights,
        }


def import_project_from_zip(zip_file: BinaryIO, db: Session) -> dict:
    """从 ZIP 文件导入完整项目。"""
    with zipfile.ZipFile(zip_file) as zf:
        required = {"project.json", "images.json", "annotations.json"}
        names = set(zf.namelist())
        if not required.issubset(names):
            missing = required - names
            raise ValueError(f"ZIP 缺少必要文件: {missing}")

        project_data = json.loads(zf.read("project.json").decode("utf-8"))
        images_data = json.loads(zf.read("images.json").decode("utf-8"))
        annotations_data = json.loads(zf.read("annotations.json").decode("utf-8"))

        # 创建项目（处理重名）
        final_name = _resolve_project_name(db, project_data["name"])
        project = Project(
            name=final_name,
            description=project_data.get("description"),
            task_type=project_data.get("task_type", "seg"),
            resize_h=project_data.get("resize_h", 2048),
            resize_w=project_data.get("resize_w", 2048),
            crop_size=project_data.get("crop_size", 640),
            overlap=project_data.get("overlap", 0.2),
        )
        db.add(project)
        db.flush()

        # 创建类别（class_index → 新的 DefectClass.id）
        class_index_to_id: dict = {}
        for cls in project_data.get("defect_classes", []):
            dc = DefectClass(
                project_id=project.id,
                class_index=cls["class_index"],
                name=cls["name"],
                color=cls.get("color", "#FF0000"),
            )
            db.add(dc)
            db.flush()
            class_index_to_id[cls["class_index"]] = dc.id

        # 复制图片文件并创建 Image 记录
        upload_dir = settings.upload_path / str(project.id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        zip_name_to_image_id: dict = {}
        imported_images = 0
        upload_dir_resolved = upload_dir.resolve()
        for img_info in images_data:
            zip_name = img_info["zip_filename"]
            # 防 ZIP slip：images.json 中的 zip_filename 来自 ZIP 内容（不可信）；
            # 用 Path.name 强制只取最后一个组件，剥掉任何 ../ 或目录分隔符
            safe_name = Path(zip_name).name
            if not safe_name or safe_name in (".", ".."):
                continue
            zip_path_in_archive = f"images/{safe_name}"
            if zip_path_in_archive not in names:
                continue

            # 防 zip bomb：声明的解压后大小超过阈值就跳过
            try:
                info = zf.getinfo(zip_path_in_archive)
                if info.file_size > _MAX_ENTRY_SIZE:
                    continue
            except KeyError:
                continue

            # 新文件名带新 uuid，避免和其他项目冲突
            new_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            target_path = upload_dir / new_name
            # 再校验一遍解析后的路径必须在 upload_dir 内（双保险）
            if not target_path.resolve().is_relative_to(upload_dir_resolved):
                continue
            with zf.open(zip_path_in_archive) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

            rel_path = f"{project.id}/{new_name}"
            cls_idx = img_info.get("class_index")
            cls_id = class_index_to_id.get(cls_idx) if cls_idx is not None else None
            image = Image(
                project_id=project.id,
                filename=img_info.get("original_filename", zip_name),
                source_relative_path=img_info.get("source_relative_path"),
                file_path=rel_path,
                width=img_info.get("width", 0),
                height=img_info.get("height", 0),
                file_size=target_path.stat().st_size,
                status=img_info.get("status", "labeled"),
                annotator=img_info.get("annotator"),
                reviewer=img_info.get("reviewer"),
                class_id=cls_id,
                content_hash=img_info.get("content_hash") or _sha256_file(target_path),
            )
            db.add(image)
            db.flush()
            zip_name_to_image_id[zip_name] = image.id
            imported_images += 1

        # 创建标注
        imported_anns = 0
        for ann in annotations_data:
            img_id = zip_name_to_image_id.get(ann["image_zip_filename"])
            cls_id = class_index_to_id.get(ann["class_index"])
            if img_id is None or cls_id is None:
                continue
            a = Annotation(
                image_id=img_id,
                class_id=cls_id,
                polygon=ann["polygon"],
                area=ann.get("area"),
                bbox=ann.get("bbox"),
                created_by=ann.get("created_by"),
            )
            db.add(a)
            imported_anns += 1

        db.commit()

        return {
            "project_id": project.id,
            "project_name": final_name,
            "renamed": final_name != project_data["name"],
            "image_count": imported_images,
            "annotation_count": imported_anns,
        }


# ============================================================================
# 合并标注包（把另一台机器的标注集合并进【已有】项目，并集去重）
# ============================================================================

def _pt_xy(p) -> tuple:
    """取多边形顶点坐标，兼容 {"x":..,"y":..} 字典 与 [x, y] 列表 两种历史格式。"""
    if isinstance(p, dict):
        return float(p.get("x", 0)), float(p.get("y", 0))
    return float(p[0]), float(p[1])


def _poly_bbox(polygon: list) -> tuple:
    pts = [_pt_xy(p) for p in polygon]
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlap(a: tuple, b: tuple) -> bool:
    """两个归一化外接框是否有交叠（无交叠的多边形不可能等价，省去栅格化）。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _poly_iou_local(p1: list, p2: list, size: int = 256) -> float:
    """在两条多边形【并集包围盒】内做局部栅格化算 IoU——尺度无关，
    再小的框（归一化尺寸 < 1/全图栅格）也能精确比较，不会塌成空 mask。"""
    import numpy as np
    import cv2
    b1, b2 = _poly_bbox(p1), _poly_bbox(p2)
    minx, miny = min(b1[0], b2[0]), min(b1[1], b2[1])
    maxx, maxy = max(b1[2], b2[2]), max(b1[3], b2[3])
    w, h = maxx - minx, maxy - miny
    if w <= 0 or h <= 0:
        return 0.0

    def _pts(poly):
        out = []
        for p in poly:
            x, y = _pt_xy(p)
            out.append([(x - minx) / w * (size - 1), (y - miny) / h * (size - 1)])
        return np.array(out, dtype=np.int32)

    m1 = np.zeros((size, size), dtype=np.uint8)
    m2 = np.zeros((size, size), dtype=np.uint8)
    cv2.fillPoly(m1, [_pts(p1)], 1)
    cv2.fillPoly(m2, [_pts(p2)], 1)
    inter = int(np.logical_and(m1, m2).sum())
    union = int(np.logical_or(m1, m2).sum())
    return inter / union if union > 0 else 0.0


def _polys_equivalent(p1: list, p2: list, iou_thresh: float = 0.85) -> bool:
    """同一张图上两条多边形是否"是同一个标注"。
    1) 坐标序列几乎一致 → 直接判重（『同名同标注』/自合并 一定命中，保证幂等）
    2) 否则在并集包围盒内做局部栅格化 IoU ≥ 阈值 → 视为同一条（容忍轻微重绘）
       位置/大小明显不同 → 保留为两条（并集）。"""
    if not p1 or not p2 or len(p1) < 3 or len(p2) < 3:
        return False
    # 精确判等快路径（坐标几乎逐点相同），尺度无关、对极小框也成立
    if len(p1) == len(p2):
        same = True
        for a, b in zip(p1, p2):
            ax, ay = _pt_xy(a)
            bx, by = _pt_xy(b)
            if abs(ax - bx) >= 1e-6 or abs(ay - by) >= 1e-6:
                same = False
                break
        if same:
            return True
    if not _bbox_overlap(_poly_bbox(p1), _poly_bbox(p2)):
        return False
    return _poly_iou_local(p1, p2) >= iou_thresh


_STATUS_ORDER = {"unlabeled": 0, "labeling": 1, "labeled": 2, "reviewed": 3}


def _max_status(a: str | None, b: str | None) -> str:
    a = a if a in _STATUS_ORDER else "unlabeled"
    b = b if b in _STATUS_ORDER else "unlabeled"
    return a if _STATUS_ORDER[a] >= _STATUS_ORDER[b] else b


def merge_pack_into_project(
    zip_file: BinaryIO, target_project_id: int, db: Session,
    dry_run: bool = False, iou_thresh: float = 0.85,
) -> dict:
    """把一个标注包（export 格式 ZIP）合并进【已有】项目。

    - 按图片内容 sha256 匹配"同一张图"（filename+尺寸兜底）
    - 命中：标注并集去重（同类别 + polygon IoU≥阈值 视为重复跳过），状态取高位，
            cls 图级标签目标为空则取包里的、两边都有且不同 → 记冲突保留目标
    - 未命中：包里独有的新标注图，连图带标注一起落地（缺图字节的超瘦包则跳过）
    - 缺失类别自动补建（按 name/class_index 映射）
    - dry_run=True 只统计不写库不落盘
    """
    project = db.query(Project).filter(Project.id == target_project_id).first()
    if not project:
        raise ValueError(f"目标项目 {target_project_id} 不存在")

    with zipfile.ZipFile(zip_file) as zf:
        required = {"project.json", "images.json", "annotations.json"}
        names = set(zf.namelist())
        if not required.issubset(names):
            raise ValueError(f"ZIP 缺少必要文件: {required - names}")

        project_data = json.loads(zf.read("project.json").decode("utf-8"))
        images_data = json.loads(zf.read("images.json").decode("utf-8"))
        annotations_data = json.loads(zf.read("annotations.json").decode("utf-8"))

        pack_task = project_data.get("task_type", "seg")
        if pack_task != project.task_type:
            raise ValueError(f"任务类型不一致：目标项目是 {project.task_type}，标注包是 {pack_task}")

        report = {
            "task_type": project.task_type,
            "pack_images": len(images_data),
            "pack_annotations": len(annotations_data),
            "matched_images": 0,
            "new_images": 0,
            "added_annotations": 0,
            "skipped_duplicates": 0,
            "new_classes": [],
            "cls_conflicts": [],
            "unmatched_no_image": 0,
            "dry_run": dry_run,
        }

        # ---- 1) 类别映射：按 name 优先、class_index 次之；缺的补建 ----
        target_classes = db.query(DefectClass).filter(DefectClass.project_id == target_project_id).all()
        name_to_dc = {dc.name: dc for dc in target_classes}
        idx_to_dc = {dc.class_index: dc for dc in target_classes}
        target_clsid_to_name = {dc.id: dc.name for dc in target_classes}
        used_indices = {dc.class_index for dc in target_classes}
        packidx_to_clsid: dict = {}
        packidx_to_name = {c.get("class_index"): c.get("name") for c in project_data.get("defect_classes", [])}
        for cls in project_data.get("defect_classes", []):
            ci = cls.get("class_index")
            cname = cls.get("name", f"class_{ci}")
            dc = name_to_dc.get(cname) or idx_to_dc.get(ci)
            if dc is not None:
                packidx_to_clsid[ci] = dc.id
            else:
                report["new_classes"].append(cname)
                if dry_run:
                    packidx_to_clsid[ci] = None
                else:
                    new_idx = ci if ci not in used_indices else (max(used_indices) + 1 if used_indices else 0)
                    used_indices.add(new_idx)
                    ndc = DefectClass(project_id=target_project_id, class_index=new_idx,
                                      name=cname, color=cls.get("color", "#FF0000"))
                    db.add(ndc)
                    db.flush()
                    name_to_dc[cname] = ndc
                    idx_to_dc[new_idx] = ndc
                    target_clsid_to_name[ndc.id] = cname
                    packidx_to_clsid[ci] = ndc.id

        # ---- 2) 目标图片按 content_hash 建索引（缺哈希现算兜底，顺手 backfill）----
        # 同一内容若有多张目标图（含未标注的重复图），选【状态最高 + 标注最多】那张当合并锚点，
        # 否则可能把已标注图的标注错算成"新增"（合并到了空的未标注重复图上）。
        upload_root = settings.upload_path
        target_images = db.query(Image).filter(Image.project_id == target_project_id).all()
        ann_counts = dict(
            db.query(Annotation.image_id, func.count(Annotation.id))
            .join(Image, Annotation.image_id == Image.id)
            .filter(Image.project_id == target_project_id)
            .group_by(Annotation.image_id).all()
        )

        def _img_rank(im):
            return (_STATUS_ORDER.get(im.status, 0), ann_counts.get(im.id, 0))

        hash_to_img: dict = {}
        fnsize_to_img: dict = {}
        for timg in target_images:
            h = timg.content_hash
            if not h:
                h = _sha256_file(upload_root / timg.file_path)
                if h and not dry_run:
                    timg.content_hash = h
            if h:
                cur = hash_to_img.get(h)
                if cur is None or _img_rank(timg) > _img_rank(cur):
                    hash_to_img[h] = timg
            key = (timg.filename, timg.width, timg.height)
            cur2 = fnsize_to_img.get(key)
            if cur2 is None or _img_rank(timg) > _img_rank(cur2):
                fnsize_to_img[key] = timg

        # ---- 3) 包内标注按图分组 ----
        anns_by_zipname = defaultdict(list)
        for a in annotations_data:
            anns_by_zipname[a.get("image_zip_filename")].append(a)

        upload_dir = upload_root / str(target_project_id)
        upload_dir_resolved = upload_dir.resolve()
        if not dry_run:
            upload_dir.mkdir(parents=True, exist_ok=True)

        # ---- 4) 逐图合并 ----
        for img_info in images_data:
            zip_name = img_info.get("zip_filename")
            chash = img_info.get("content_hash")
            tgt = hash_to_img.get(chash) if chash else None
            if tgt is None:
                tgt = fnsize_to_img.get((img_info.get("original_filename"), img_info.get("width"), img_info.get("height")))
            incoming_anns = anns_by_zipname.get(zip_name, [])

            if tgt is not None:
                # —— 命中：标注并集去重 ——
                report["matched_images"] += 1
                accepted: dict = defaultdict(list)
                for ex in tgt.annotations:
                    accepted[ex.class_id].append(ex.polygon)
                for a in incoming_anns:
                    clsid = packidx_to_clsid.get(a.get("class_index"))
                    poly = a.get("polygon") or []
                    pool = accepted.get(clsid, []) if clsid is not None else []
                    if any(_polys_equivalent(poly, ep, iou_thresh) for ep in pool):
                        report["skipped_duplicates"] += 1
                        continue
                    report["added_annotations"] += 1
                    if clsid is not None:
                        accepted[clsid].append(poly)
                        if not dry_run:
                            db.add(Annotation(image_id=tgt.id, class_id=clsid, polygon=poly,
                                              area=a.get("area"), bbox=a.get("bbox"), created_by=a.get("created_by")))
                new_status = _max_status(tgt.status, img_info.get("status", "unlabeled"))
                if not dry_run and new_status != tgt.status:
                    tgt.status = new_status
                if project.task_type == "cls":
                    in_ci = img_info.get("class_index")
                    in_clsid = packidx_to_clsid.get(in_ci) if in_ci is not None else None
                    if in_clsid is not None:
                        if tgt.class_id is None:
                            if not dry_run:
                                tgt.class_id = in_clsid
                        elif tgt.class_id != in_clsid:
                            report["cls_conflicts"].append({
                                "filename": tgt.filename,
                                "target_class": target_clsid_to_name.get(tgt.class_id, str(tgt.class_id)),
                                "incoming_class": packidx_to_name.get(in_ci, str(in_ci)),
                            })
            else:
                # —— 未命中：包里独有的新标注图，连图带标注落地 ——
                safe_name = Path(zip_name).name if zip_name else ""
                zip_path_in_archive = f"images/{safe_name}"
                if not safe_name or safe_name in (".", "..") or zip_path_in_archive not in names:
                    report["unmatched_no_image"] += 1
                    continue
                if dry_run:
                    report["new_images"] += 1
                    report["added_annotations"] += len(incoming_anns)
                    continue
                try:
                    info = zf.getinfo(zip_path_in_archive)
                    if info.file_size > _MAX_ENTRY_SIZE:
                        report["unmatched_no_image"] += 1
                        continue
                except KeyError:
                    report["unmatched_no_image"] += 1
                    continue
                new_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
                target_path = upload_dir / new_name
                if not target_path.resolve().is_relative_to(upload_dir_resolved):
                    report["unmatched_no_image"] += 1
                    continue
                with zf.open(zip_path_in_archive) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                cls_idx = img_info.get("class_index")
                cls_id = packidx_to_clsid.get(cls_idx) if cls_idx is not None else None
                nimg = Image(
                    project_id=target_project_id,
                    filename=img_info.get("original_filename", safe_name),
                    file_path=f"{target_project_id}/{new_name}",
                    width=img_info.get("width", 0),
                    height=img_info.get("height", 0),
                    file_size=target_path.stat().st_size,
                    status=img_info.get("status", "labeled"),
                    annotator=img_info.get("annotator"),
                    reviewer=img_info.get("reviewer"),
                    class_id=cls_id,
                    content_hash=chash or _sha256_file(target_path),
                )
                db.add(nimg)
                db.flush()
                report["new_images"] += 1
                for a in incoming_anns:
                    clsid = packidx_to_clsid.get(a.get("class_index"))
                    if clsid is None:
                        continue
                    db.add(Annotation(image_id=nimg.id, class_id=clsid, polygon=a.get("polygon") or [],
                                      area=a.get("area"), bbox=a.get("bbox"), created_by=a.get("created_by")))
                    report["added_annotations"] += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return report
