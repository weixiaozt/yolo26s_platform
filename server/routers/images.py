# -*- coding: utf-8 -*-
"""
图像管理 API
"""

import shutil
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models.project import Project
from ..models.image import Image
from ..models.annotation import Annotation
from ..schemas.image import ImageOut, ImageListOut, ImageStatusUpdate

router = APIRouter(prefix="/api", tags=["图像管理"])

# 支持的图像格式
ALLOWED_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def _make_thumbnail(src_path: Path, thumb_path: Path, max_size: int = 256):
    """生成缩略图"""
    img = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return
    h, w = img.shape[:2]
    scale = min(max_size / w, max_size / h, 1.0)
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(thumb_path), img)


@router.post("/projects/{project_id}/images/upload", response_model=list[ImageOut])
async def upload_images(
    project_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """批量上传图像"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    uploaded = []
    project_dir = settings.upload_path / str(project_id)
    thumb_dir = project_dir / "thumbs"
    project_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    max_size = settings.MAX_UPLOAD_SIZE

    for file in files:
        # 检查格式
        if not file.filename:
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            continue

        # 上传前如果框架已提供 size，先快速拒绝过大文件，避免无谓读盘
        if file.size is not None and file.size > max_size:
            print(f"[upload] skipped {file.filename}: size {file.size} > MAX_UPLOAD_SIZE {max_size}")
            continue

        # 生成唯一文件名，避免重名冲突
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = project_dir / unique_name
        thumb_path = thumb_dir / f"{unique_name}.jpg"

        # 保存文件（流式读取以便提前发现超限，防止 OOM）
        content_chunks: list[bytes] = []
        total = 0
        oversized = False
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                oversized = True
                break
            content_chunks.append(chunk)
        if oversized:
            print(f"[upload] skipped {file.filename}: exceeded MAX_UPLOAD_SIZE {max_size} mid-stream")
            continue
        content = b"".join(content_chunks)
        save_path.write_bytes(content)

        # 读取图像尺寸
        img_array = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
        if img_array is None:
            save_path.unlink(missing_ok=True)
            continue
        h, w = img_array.shape[:2]

        # 生成缩略图
        _make_thumbnail(save_path, thumb_path, settings.THUMB_SIZE)

        # 写数据库
        rel_path = f"{project_id}/{unique_name}"
        rel_thumb = f"{project_id}/thumbs/{unique_name}.jpg"
        image = Image(
            project_id=project_id,
            filename=file.filename,
            file_path=rel_path,
            thumb_path=rel_thumb,
            width=w,
            height=h,
            file_size=len(content),
        )
        db.add(image)
        db.flush()
        uploaded.append(image)

    db.commit()

    return [
        ImageOut(
            id=img.id,
            project_id=img.project_id,
            filename=img.filename,
            width=img.width,
            height=img.height,
            file_size=img.file_size,
            status=img.status,
            annotator=img.annotator,
            reviewer=img.reviewer,
            created_at=img.created_at,
            annotation_count=0,
        )
        for img in uploaded
    ]


@router.get("/projects/{project_id}/images", response_model=ImageListOut)
def list_images(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    status: str = Query(default=None, description="按标注状态过滤"),
    class_id: int | None = Query(default=None, description="按图像分类 id 过滤（cls 项目专用）"),
    db: Session = Depends(get_db),
):
    """获取图像列表（分页）"""
    query = db.query(Image).filter(Image.project_id == project_id)
    if status:
        query = query.filter(Image.status == status)
    if class_id is not None:
        query = query.filter(Image.class_id == class_id)

    total = query.count()
    images = (
        query
        .order_by(Image.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 批量查询标注数
    image_ids = [img.id for img in images]
    if image_ids:
        ann_counts = dict(
            db.query(Annotation.image_id, func.count(Annotation.id))
            .filter(Annotation.image_id.in_(image_ids))
            .group_by(Annotation.image_id)
            .all()
        )
    else:
        ann_counts = {}

    items = [
        ImageOut(
            id=img.id,
            project_id=img.project_id,
            filename=img.filename,
            width=img.width,
            height=img.height,
            file_size=img.file_size,
            status=img.status,
            annotator=img.annotator,
            reviewer=img.reviewer,
            created_at=img.created_at,
            annotation_count=ann_counts.get(img.id, 0),
            class_id=img.class_id,
        )
        for img in images
    ]

    return ImageListOut(total=total, page=page, page_size=page_size, items=items)


@router.get("/images/{image_id}/file")
def get_image_file(
    image_id: int,
    thumb: bool = Query(default=False, description="是否返回缩略图"),
    db: Session = Depends(get_db),
):
    """获取图像文件（原图或缩略图）。

    file_path 来自 DB（正常流程下由我们自己写入），但加 resolve + is_relative_to
    防御万一 DB 被改后通过本端点读取 STORAGE_ROOT 之外的任意文件。本接口默认
    不走 AuthMiddleware（见 main.py 白名单），所以匿名可访问，更需要这层校验。
    """
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图像不存在")

    upload_root = settings.upload_path.resolve()
    if thumb and image.thumb_path:
        file_path = (settings.upload_path / image.thumb_path).resolve()
    else:
        file_path = (settings.upload_path / image.file_path).resolve()

    try:
        file_path.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(str(file_path))


@router.put("/images/{image_id}/status")
def update_image_status(
    image_id: int,
    body: ImageStatusUpdate,
    db: Session = Depends(get_db),
):
    """更新图像标注状态"""
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图像不存在")

    valid_statuses = {"unlabeled", "labeling", "labeled", "reviewed"}
    if body.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态: {body.status}")

    image.status = body.status
    if body.annotator is not None:
        image.annotator = body.annotator
    if body.reviewer is not None:
        image.reviewer = body.reviewer

    db.commit()
    return {"ok": True}


@router.put("/projects/{project_id}/images/batch-class")
def batch_set_class(
    project_id: int,
    body: dict,  # {"image_ids": [int], "class_id": int|null, "annotator": str|null}
    db: Session = Depends(get_db),
):
    """
    批量给图片打分类标签（cls 项目专用）。
    image_ids: 要打标的图片 id 列表
    class_id: 类别 id（null 表示清空标签 → unlabeled）
    """
    from ..models.project import Project
    from ..models.defect_class import DefectClass

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.task_type != "cls":
        raise HTTPException(status_code=400, detail=f"仅分类项目支持批量打标，当前 task_type={project.task_type}")

    image_ids = body.get("image_ids") or []
    class_id = body.get("class_id")
    annotator = body.get("annotator")

    if not isinstance(image_ids, list) or not image_ids:
        raise HTTPException(status_code=400, detail="image_ids 不能为空")

    # 校验 class_id 属于项目
    if class_id is not None:
        ok = (
            db.query(DefectClass.id)
            .filter(DefectClass.id == class_id, DefectClass.project_id == project_id)
            .first()
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"class_id {class_id} 不属于项目 {project_id}")

    # 批量更新
    images = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.id.in_(image_ids))
        .all()
    )
    updated = 0
    for img in images:
        img.class_id = class_id
        # 状态：有 class_id → labeled，否则 → unlabeled
        if img.status != "reviewed":  # OK 标记不覆盖
            img.status = "labeled" if class_id is not None else "unlabeled"
        if annotator:
            img.annotator = annotator
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated}


@router.get("/projects/{project_id}/images/class-stats")
def get_class_stats(project_id: int, db: Session = Depends(get_db)):
    """
    返回项目每个类别下的图片计数 + 未分类的数量（cls 项目右侧统计面板用）。
    返回:
        {"by_class": {class_id: count, ...}, "unlabeled": int, "total": int}
    """
    from sqlalchemy import func
    rows = (
        db.query(Image.class_id, func.count(Image.id))
        .filter(Image.project_id == project_id)
        .group_by(Image.class_id)
        .all()
    )
    by_class: dict[int, int] = {}
    unlabeled = 0
    total = 0
    for cid, cnt in rows:
        total += cnt
        if cid is None:
            unlabeled += cnt
        else:
            by_class[int(cid)] = int(cnt)
    return {"by_class": by_class, "unlabeled": unlabeled, "total": total}


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: int, db: Session = Depends(get_db)):
    """删除图像及其标注 + 磁盘文件。

    file_path / thumb_path 来自 DB。写操作（unlink）比读取更敏感——一旦 DB 行
    被改成 '../../../something'，没有边界校验就会删掉 STORAGE_ROOT 之外的文件。
    """
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图像不存在")

    upload_root = settings.upload_path.resolve()

    def _safe_unlink(rel: str | None) -> None:
        if not rel:
            return
        try:
            target = (settings.upload_path / rel).resolve()
            target.relative_to(upload_root)
        except (ValueError, OSError):
            return
        target.unlink(missing_ok=True)

    _safe_unlink(image.file_path)
    _safe_unlink(image.thumb_path)

    db.delete(image)
    db.commit()
