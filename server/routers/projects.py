# -*- coding: utf-8 -*-
"""
项目管理 API
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models.project import Project
from ..models.defect_class import DefectClass
from ..models.image import Image
from ..models.annotation import Annotation
from ..schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut, ProjectStats, DefectClassCreate, DefectClassOut,
)

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    """创建项目（含缺陷类别）"""
    project = Project(
        name=body.name,
        description=body.description,
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


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """删除项目（级联删除所有关联数据）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(project)
    db.commit()


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
