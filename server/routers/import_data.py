# -*- coding: utf-8 -*-
"""
标注导入 API
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models.project import Project
from ..models.defect_class import DefectClass
from ..models.image import Image
from ..models.annotation import Annotation

router = APIRouter(prefix="/api/import", tags=["标注导入"])

SUPPORTED_IMG_EXTS = {'.bmp', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}


@router.post("/scan-xml")
async def scan_xml_classes_api(files: List[UploadFile] = File(...)):
    """
    上传 XML 文件，自动扫描提取所有类别名。
    返回 {类别名: 出现次数}
    """
    import tempfile, os
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        for f in files:
            if f.filename and f.filename.endswith('.xml'):
                content = await f.read()
                (tmp_dir / f.filename).write_bytes(content)

        from ..services.import_service import scan_xml_classes
        class_counts = scan_xml_classes(str(tmp_dir))
        return {"classes": class_counts}
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


@router.post("/auto-mapping")
async def auto_mapping_api(
    xml_files: List[UploadFile] = File(...),
    mask_files: List[UploadFile] = File(...),
):
    """
    上传 XML + Mask 文件，自动检测像素值→类别名映射。
    返回 {像素值: 类别名}
    """
    import tempfile
    tmp_xml = Path(tempfile.mkdtemp())
    tmp_mask = Path(tempfile.mkdtemp())
    try:
        for f in xml_files:
            if f.filename and f.filename.endswith('.xml'):
                content = await f.read()
                (tmp_xml / f.filename).write_bytes(content)
        for f in mask_files:
            if f.filename:
                content = await f.read()
                (tmp_mask / f.filename).write_bytes(content)

        from ..services.import_service import auto_detect_pixel_class_mapping
        mapping = auto_detect_pixel_class_mapping(str(tmp_xml), str(tmp_mask))
        # 返回 {像素值(str): 类别名}
        return {"mapping": {str(k): v for k, v in sorted(mapping.items())}}
    finally:
        shutil.rmtree(str(tmp_xml), ignore_errors=True)
        shutil.rmtree(str(tmp_mask), ignore_errors=True)


@router.post("/run")
async def import_project(
    project_name: str = Form(...),
    description: str = Form(default=""),
    resize_h: int = Form(default=2048),
    resize_w: int = Form(default=2048),
    crop_size: int = Form(default=640),
    overlap: float = Form(default=0.2),
    class_mapping_json: str = Form(...),  # JSON: {"像素值": {"class_index": 0, "name": "崩边", "color": "#FF0000"}}
    images: List[UploadFile] = File(...),
    masks: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    执行导入：创建项目 + 导入图片 + 转换标注

    class_mapping_json 格式:
    {
        "1": {"class_index": 0, "name": "崩边", "color": "#FF0000"},
        "2": {"class_index": 1, "name": "裂纹", "color": "#00FF00"},
        ...
    }
    """
    # 解析类别映射
    try:
        class_mapping_raw = json.loads(class_mapping_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="class_mapping_json 格式错误")

    # pixel_val → class_index
    pixel_to_index = {}
    class_defs = {}  # class_index → {name, color}
    for pv_str, info in class_mapping_raw.items():
        pv = int(pv_str)
        ci = int(info["class_index"])
        pixel_to_index[pv] = ci
        class_defs[ci] = {"name": info["name"], "color": info.get("color", "#FF0000")}

    if not pixel_to_index:
        raise HTTPException(status_code=400, detail="至少需要一个类别映射")

    # 1. 创建项目
    project = Project(
        name=project_name,
        description=description or "导入项目",
        resize_h=resize_h, resize_w=resize_w,
        crop_size=crop_size, overlap=overlap,
    )
    db.add(project)
    db.flush()

    # 2. 创建类别
    for ci, info in sorted(class_defs.items()):
        dc = DefectClass(
            project_id=project.id,
            class_index=ci,
            name=info["name"],
            color=info["color"],
        )
        db.add(dc)

    # 3. 保存图片和 Mask，转换标注
    upload_dir = settings.upload_path / str(project.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 建立 mask 文件名索引（stem → UploadFile）
    mask_map = {}
    for mf in masks:
        if mf.filename:
            stem = Path(mf.filename).stem
            mask_map[stem] = mf

    from ..services.import_service import mask_to_polygons

    stats = {"total": 0, "with_ann": 0, "total_polygons": 0, "skipped": 0}

    for img_file in images:
        if not img_file.filename:
            continue
        ext = Path(img_file.filename).suffix.lower()
        if ext not in SUPPORTED_IMG_EXTS:
            continue

        stats["total"] += 1
        stem = Path(img_file.filename).stem

        # 保存原图
        img_content = await img_file.read()
        saved_name = f"{uuid.uuid4().hex[:8]}_{img_file.filename}"
        img_saved_path = upload_dir / saved_name
        img_saved_path.write_bytes(img_content)

        # 获取图像尺寸
        import cv2, numpy as np
        img_array = cv2.imdecode(np.frombuffer(img_content, np.uint8), cv2.IMREAD_UNCHANGED)
        if img_array is None:
            stats["skipped"] += 1
            continue
        h, w = img_array.shape[:2]

        # 创建 Image 记录
        image = Image(
            project_id=project.id,
            filename=img_file.filename,
            file_path=str(img_saved_path),
            width=w, height=h,
            status="unlabeled",
        )
        db.add(image)
        db.flush()

        # 查找对应 Mask
        mask_file = mask_map.get(stem)
        if not mask_file:
            continue

        # 保存 Mask 到临时文件
        mask_content = await mask_file.read()
        # reset for potential re-read
        await mask_file.seek(0)
        import tempfile
        tmp_mask_path = Path(tempfile.mktemp(suffix='.png'))
        tmp_mask_path.write_bytes(mask_content)

        try:
            polygons = mask_to_polygons(str(tmp_mask_path), pixel_to_index)

            # Mask 尺寸可能和原图不同，需要坐标缩放
            mask_img = cv2.imdecode(np.frombuffer(mask_content, np.uint8), cv2.IMREAD_UNCHANGED)
            if mask_img is not None:
                mh, mw = mask_img.shape[:2] if len(mask_img.shape) == 2 else mask_img.shape[:2]
                sx = w / mw if mw != w else 1.0
                sy = h / mh if mh != h else 1.0
            else:
                sx, sy = 1.0, 1.0

            if polygons:
                for poly in polygons:
                    # 缩放坐标到原图尺寸
                    scaled_points = [[p[0] * sx, p[1] * sy] for p in poly["points"]]
                    ann = Annotation(
                        image_id=image.id,
                        class_index=poly["class_index"],
                        polygon=scaled_points,
                    )
                    db.add(ann)
                    stats["total_polygons"] += 1

                image.status = "labeled"
                stats["with_ann"] += 1
        finally:
            tmp_mask_path.unlink(missing_ok=True)

    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "stats": stats,
    }
