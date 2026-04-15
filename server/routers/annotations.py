# -*- coding: utf-8 -*-
"""
标注管理 API
============
核心设计：全量覆盖保存模式。
前端标注编辑器点击保存时，提交该图像的全部标注数组，
后端在一个事务中删除旧标注并插入新标注，保证数据一致性。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.image import Image
from ..models.annotation import Annotation
from ..models.defect_class import DefectClass
from ..schemas.annotation import AnnotationOut, AnnotationBatchSave

router = APIRouter(prefix="/api", tags=["标注管理"])


def _annotation_to_out(ann: Annotation) -> AnnotationOut:
    """将 ORM 对象转换为输出 schema（附带类别信息）"""
    dc = ann.defect_class
    return AnnotationOut(
        id=ann.id,
        image_id=ann.image_id,
        class_id=ann.class_id,
        polygon=ann.polygon,
        area=ann.area,
        bbox=ann.bbox,
        created_by=ann.created_by,
        created_at=ann.created_at,
        updated_at=ann.updated_at,
        class_name=dc.name if dc else None,
        class_color=dc.color if dc else None,
    )


@router.get("/images/{image_id}/annotations", response_model=list[AnnotationOut])
def get_annotations(image_id: int, db: Session = Depends(get_db)):
    """获取某张图像的全部标注"""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图像不存在")

    annotations = (
        db.query(Annotation)
        .filter(Annotation.image_id == image_id)
        .order_by(Annotation.id)
        .all()
    )
    return [_annotation_to_out(ann) for ann in annotations]


@router.post("/images/{image_id}/annotations", response_model=list[AnnotationOut])
def save_annotations(
    image_id: int,
    body: AnnotationBatchSave,
    db: Session = Depends(get_db),
):
    """
    全量覆盖保存标注。
    前端一次提交该图像的所有标注，后端先删旧再插新。

    流程：
        1. 验证图像存在
        2. 验证所有 class_id 合法
        3. 事务内：删除旧标注 → 插入新标注
        4. 更新图像状态为 labeling/labeled
    """
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图像不存在")

    # 验证 class_id 合法性
    valid_class_ids = set(
        cid for (cid,) in
        db.query(DefectClass.id).filter(DefectClass.project_id == image.project_id).all()
    )
    for ann in body.annotations:
        if ann.class_id not in valid_class_ids:
            raise HTTPException(
                status_code=400,
                detail=f"class_id {ann.class_id} 不属于项目 {image.project_id}"
            )

    # 事务：删旧 → 插新
    db.query(Annotation).filter(Annotation.image_id == image_id).delete()

    new_annotations = []
    for ann_data in body.annotations:
        ann = Annotation(
            image_id=image_id,
            class_id=ann_data.class_id,
            polygon=[{"x": p.x, "y": p.y} for p in ann_data.polygon],
            area=ann_data.area,
            bbox=ann_data.bbox,
            created_by=body.annotator or ann_data.created_by,
        )
        db.add(ann)
        db.flush()
        new_annotations.append(ann)

    # 更新图像状态
    if len(body.annotations) > 0:
        image.status = "labeled"
    else:
        image.status = "unlabeled"

    if body.annotator:
        image.annotator = body.annotator

    db.commit()

    # 重新查询以获取完整关系数据
    result = (
        db.query(Annotation)
        .filter(Annotation.image_id == image_id)
        .order_by(Annotation.id)
        .all()
    )
    return [_annotation_to_out(ann) for ann in result]


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    """删除单个标注"""
    ann = db.query(Annotation).filter(Annotation.id == annotation_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="标注不存在")
    db.delete(ann)
    db.commit()
