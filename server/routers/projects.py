# -*- coding: utf-8 -*-
"""
项目管理 API
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..models.project import Project
from ..models.defect_class import DefectClass
from ..models.image import Image
from ..models.annotation import Annotation
from ..models.train_task import TrainTask
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut, ProjectStats, DefectClassCreate, DefectClassOut,
)
from ..services.project_package import export_project_to_zip, import_project_from_zip
from ..services.project_convert import convert_project_task_type

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    """创建项目（含缺陷类别）"""
    project = Project(
        name=body.name,
        description=body.description,
        task_type=body.task_type,
        resize_h=body.resize_h,
        resize_w=body.resize_w,
        crop_size=body.crop_size,
        overlap=body.overlap,
    )
    db.add(project)
    db.flush()  # 获取 project.id

    for cls in body.class_names:
        dc = DefectClass(
            project_id=project.id,
            class_index=cls.class_index,
            name=cls.name,
            color=cls.color,
        )
        db.add(dc)

    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    """获取项目列表"""
    projects = (
        db.query(Project)
        .options(joinedload(Project.defect_classes))
        .order_by(Project.created_at.desc())
        .all()
    )
    return projects


@router.get("/{project_id}", response_model=ProjectStats)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """获取项目详情（含统计信息）"""
    project = (
        db.query(Project)
        .options(joinedload(Project.defect_classes))
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 统计图像状态分布
    status_counts = (
        db.query(Image.status, func.count(Image.id))
        .filter(Image.project_id == project_id)
        .group_by(Image.status)
        .all()
    )
    counts = dict(status_counts)
    total_images = sum(counts.values())

    # 统计标注总数
    total_annotations = (
        db.query(func.count(Annotation.id))
        .join(Image, Annotation.image_id == Image.id)
        .filter(Image.project_id == project_id)
        .scalar()
    )

    return ProjectStats(
        **{c.key: getattr(project, c.key) for c in Project.__table__.columns},
        defect_classes=[DefectClassOut.model_validate(dc) for dc in project.defect_classes],
        total_images=total_images,
        unlabeled_count=counts.get("unlabeled", 0),
        labeling_count=counts.get("labeling", 0),
        labeled_count=counts.get("labeled", 0),
        reviewed_count=counts.get("reviewed", 0),
        total_annotations=total_annotations or 0,
    )


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    """更新项目信息"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)

    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/train-config-cache")
def save_train_config_cache(
    project_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    保存项目级训练参数缓存（用户在训练配置页点"保存为默认"时调用）。

    body 是整个 TrainConfig 表单的 JSON，下次进入训练页直接加载。
    传 null 或 {} 表示清空。
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.last_train_config = body or None
    db.commit()
    return {"ok": True, "saved_at": project.updated_at.isoformat() if project.updated_at else None}


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """删除项目（级联删除 DB 数据 + 磁盘文件）。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 先抓出磁盘上要清的路径（DB 删完后就查不到 task_id 了）
    upload_dir = settings.upload_path / str(project_id)
    train_dirs: list[Path] = []
    for t in db.query(TrainTask).filter(TrainTask.project_id == project_id).all():
        run_root = Path(settings.STORAGE_ROOT).resolve() / settings.RUNS_DIR / f"task_{t.id}"
        if run_root.exists():
            train_dirs.append(run_root)

    db.delete(project)
    db.commit()

    # 磁盘清理失败不回滚 DB —— DB 已经一致，文件残留下次再清比 DB 半残更可控
    upload_root = settings.upload_path.resolve()
    runs_root = (Path(settings.STORAGE_ROOT).resolve() / settings.RUNS_DIR).resolve()
    try:
        if upload_dir.exists() and upload_dir.resolve().is_relative_to(upload_root):
            shutil.rmtree(str(upload_dir), ignore_errors=True)
    except Exception:
        log.exception("delete_project: failed to rm upload_dir %s", upload_dir)
    for d in train_dirs:
        try:
            if d.resolve().is_relative_to(runs_root):
                shutil.rmtree(str(d), ignore_errors=True)
        except Exception:
            log.exception("delete_project: failed to rm train_dir %s", d)


@router.get("/{project_id}/export-package")
def export_package(project_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """导出项目为 ZIP（仅已标注图片）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    tmp_dir = Path(tempfile.mkdtemp(prefix="proj_export_"))
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name)
    out_path = tmp_dir / f"{safe_stem}_export.zip"

    try:
        export_project_to_zip(project_id, db, out_path)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        log.exception("export_project_to_zip failed for project_id=%s", project_id)
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

    # 让 FileResponse 写完后再把临时目录删掉，避免泄漏
    background_tasks.add_task(shutil.rmtree, str(tmp_dir), ignore_errors=True)

    download_name = f"{project.name}_export.zip"
    return FileResponse(
        str(out_path),
        media_type="application/zip",
        filename=download_name,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(download_name)}"},
    )


@router.post("/import-package")
async def import_package(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """从 ZIP 导入完整项目（含图片和标注）"""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 文件")

    # mkstemp 是原子创建（O_EXCL），避免 mktemp 的 race condition
    fd, tmp_str = tempfile.mkstemp(suffix=".zip", prefix="proj_import_")
    tmp_path = Path(tmp_str)
    try:
        # mkstemp 返回的 fd 我们不直接用，下面用 write_bytes 写入路径
        os.close(fd)
        content = await file.read()
        tmp_path.write_bytes(content)

        with open(tmp_path, "rb") as f:
            result = import_project_from_zip(f, db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("import_project_from_zip failed for upload=%s", file.filename)
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/{project_id}/convert-task-type")
def convert_task_type(
    project_id: int,
    target_type: str = Form(..., description="目标类型: seg / det"),
    mode: str = Form(default="copy", description="inplace=原地 / copy=复制为新项目"),
    new_name: str = Form(default="", description="复制模式下的新项目名"),
    db: Session = Depends(get_db),
):
    """
    转换项目任务类型（seg ↔ det）。
    标注数据本身不需要修改 —— 平台标注统一以 polygon 存储，
    det 模式下是 4 点矩形，对 seg 训练同样合法。
    """
    try:
        result = convert_project_task_type(
            project_id=project_id,
            target_type=target_type,
            mode=mode,
            db=db,
            new_name=new_name or None,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("convert_project_task_type failed project_id=%s target=%s", project_id, target_type)
        raise HTTPException(status_code=500, detail=f"转换失败: {e}")


@router.post("/{project_id}/classes", response_model=DefectClassOut, status_code=201)
def add_defect_class(project_id: int, body: DefectClassCreate, db: Session = Depends(get_db)):
    """添加缺陷类别"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 检查 class_index 是否重复
    existing = (
        db.query(DefectClass)
        .filter(DefectClass.project_id == project_id, DefectClass.class_index == body.class_index)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"class_index {body.class_index} 已存在")

    dc = DefectClass(project_id=project_id, **body.model_dump())
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


@router.put("/{project_id}/classes/{class_id}", response_model=DefectClassOut)
def update_defect_class(project_id: int, class_id: int, body: DefectClassCreate, db: Session = Depends(get_db)):
    """修改缺陷类别（名称、颜色）"""
    dc = db.query(DefectClass).filter(DefectClass.id == class_id, DefectClass.project_id == project_id).first()
    if not dc:
        raise HTTPException(status_code=404, detail="类别不存在")
    dc.name = body.name
    dc.color = body.color
    db.commit()
    db.refresh(dc)
    return dc


@router.delete("/{project_id}/classes/{class_id}")
def delete_defect_class(project_id: int, class_id: int, db: Session = Depends(get_db)):
    """删除缺陷类别（检查是否有标注引用）"""
    dc = db.query(DefectClass).filter(DefectClass.id == class_id, DefectClass.project_id == project_id).first()
    if not dc:
        raise HTTPException(status_code=404, detail="类别不存在")

    # 检查是否有标注使用了该类别
    ann_count = (
        db.query(func.count(Annotation.id))
        .join(Image, Annotation.image_id == Image.id)
        .filter(Image.project_id == project_id, Annotation.class_index == dc.class_index)
        .scalar()
    )
    if ann_count and ann_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"该类别下有 {ann_count} 个标注，请先删除相关标注再删除类别"
        )

    db.delete(dc)
    db.commit()
    return {"ok": True, "message": f"类别 {dc.name} 已删除"}
