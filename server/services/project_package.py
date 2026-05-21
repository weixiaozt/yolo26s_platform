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

import json
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from ..config import settings
from ..models.project import Project
from ..models.defect_class import DefectClass
from ..models.image import Image
from ..models.annotation import Annotation

# 单个 ZIP 内文件解压后大小上限（防 zip bomb），200MB 远超任何真实工业图
_MAX_ENTRY_SIZE = 200 * 1024 * 1024


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

            # cls 图级标签：用 class_index（跨项目可移植）；非 cls 留空
            images_data.append({
                "zip_filename": zip_img_name,
                "original_filename": img.filename,
                "width": img.width,
                "height": img.height,
                "status": img.status,
                "annotator": img.annotator,
                "reviewer": img.reviewer,
                "class_index": class_id_to_index.get(img.class_id) if img.class_id else None,
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
                file_path=rel_path,
                width=img_info.get("width", 0),
                height=img_info.get("height", 0),
                file_size=target_path.stat().st_size,
                status=img_info.get("status", "labeled"),
                annotator=img_info.get("annotator"),
                reviewer=img_info.get("reviewer"),
                class_id=cls_id,
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
