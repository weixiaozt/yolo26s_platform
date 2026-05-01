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
    class_index_to_id = {}  # class_index → defect_class.id
    for ci, info in sorted(class_defs.items()):
        dc = DefectClass(
            project_id=project.id,
            class_index=ci,
            name=info["name"],
            color=info["color"],
        )
        db.add(dc)
        db.flush()  # 获取 dc.id
        class_index_to_id[ci] = dc.id

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

        # 创建 Image 记录（file_path 存相对路径）
        rel_path = f"{project.id}/{saved_name}"
        image = Image(
            project_id=project.id,
            filename=img_file.filename,
            file_path=rel_path,
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

            if polygons:
                for poly in polygons:
                    # 坐标已归一化到 0~1，直接存储
                    ann = Annotation(
                        image_id=image.id,
                        class_id=class_index_to_id.get(poly["class_index"], list(class_index_to_id.values())[0]),
                        polygon=poly["points"],
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


# ===========================================================
# 目标检测（Object Detection）VOC XML 导入
# ===========================================================

@router.post("/voc-scan")
async def scan_voc_classes_api(files: List[UploadFile] = File(...)):
    """
    上传 Pascal VOC 格式 XML 文件，扫描所有类别名 + bbox 数。
    返回 {类别名: bbox 总数}
    """
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        for f in files:
            if f.filename and f.filename.lower().endswith('.xml'):
                content = await f.read()
                (tmp_dir / f.filename).write_bytes(content)

        from ..services.import_service import scan_xml_classes
        class_counts = scan_xml_classes(str(tmp_dir))
        return {"classes": class_counts}
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


@router.post("/voc-run")
async def import_voc_project(
    project_name: str = Form(...),
    description: str = Form(default=""),
    crop_size: int = Form(default=640),
    task_type: str = Form(default="det"),   # 'det' 或 'obb'，标注存储格式相同（4 点 polygon）
    class_mapping_json: str = Form(...),  # JSON: {"panel": {"class_index": 0, "color": "#FF0000"}}
    images: List[UploadFile] = File(...),
    xmls: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    执行目标检测项目导入：创建项目 + 导入图片 + 转换 VOC bbox → 4点多边形

    task_type:
        - 'det': 普通目标检测，训练 YOLO det
        - 'obb': 旋转目标检测，训练 YOLO OBB（标签由 minAreaRect 自动转旋转矩形；
                即使源 bbox 是 axis-aligned，配合 degrees=180 增强模型也能学到角度）

    class_mapping_json 格式（key 是类别名，不是像素值）：
    {
        "panel": {"class_index": 0, "color": "#FF0000"},
        "defect": {"class_index": 1, "color": "#00FF00"}
    }
    """
    if task_type not in ("det", "obb"):
        raise HTTPException(status_code=400, detail="task_type 必须是 det 或 obb")
    # 解析类别映射
    try:
        class_mapping_raw = json.loads(class_mapping_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="class_mapping_json 格式错误")

    if not class_mapping_raw:
        raise HTTPException(status_code=400, detail="至少需要一个类别映射")

    # name → class_index, name → color
    name_to_index = {}
    class_defs = {}  # class_index → {name, color}
    for cls_name, info in class_mapping_raw.items():
        try:
            ci = int(info["class_index"])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"类别 {cls_name} 缺少 class_index")
        name_to_index[cls_name] = ci
        class_defs[ci] = {"name": cls_name, "color": info.get("color", "#FF0000")}

    # 1. 创建项目（task_type 由参数决定）
    default_desc = "旋转目标检测项目" if task_type == "obb" else "目标检测项目"
    project = Project(
        name=project_name,
        description=description or default_desc,
        task_type=task_type,
        resize_h=crop_size,
        resize_w=crop_size,
        crop_size=crop_size,
        overlap=0.0,
    )
    db.add(project)
    db.flush()

    # 2. 创建类别
    class_index_to_id = {}
    for ci, info in sorted(class_defs.items()):
        dc = DefectClass(
            project_id=project.id,
            class_index=ci,
            name=info["name"],
            color=info["color"],
        )
        db.add(dc)
        db.flush()
        class_index_to_id[ci] = dc.id

    # 3. 保存图片，处理 XML
    upload_dir = settings.upload_path / str(project.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 建立 XML 索引（stem → UploadFile）
    xml_map = {}
    for xf in xmls:
        if xf.filename and xf.filename.lower().endswith('.xml'):
            stem = Path(xf.filename).stem
            xml_map[stem] = xf

    from ..services.import_service import parse_voc_xml, bbox_to_polygon4

    stats = {"total": 0, "with_ann": 0, "total_boxes": 0, "skipped_no_xml": 0,
             "skipped_unknown_class": 0, "skipped_image_decode": 0}

    import tempfile

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
            stats["skipped_image_decode"] += 1
            img_saved_path.unlink(missing_ok=True)
            continue
        h, w = img_array.shape[:2]

        # 创建 Image 记录
        rel_path = f"{project.id}/{saved_name}"
        image = Image(
            project_id=project.id,
            filename=img_file.filename,
            file_path=rel_path,
            width=w, height=h,
            status="unlabeled",
        )
        db.add(image)
        db.flush()

        # 查找对应 XML
        xml_file = xml_map.get(stem)
        if not xml_file:
            stats["skipped_no_xml"] += 1
            continue

        # 解析 XML
        xml_content = await xml_file.read()
        await xml_file.seek(0)
        tmp_xml = Path(tempfile.mktemp(suffix='.xml'))
        tmp_xml.write_bytes(xml_content)

        try:
            voc = parse_voc_xml(str(tmp_xml))
            xml_w = voc["width"] or w
            xml_h = voc["height"] or h

            box_count = 0
            for obj in voc["objects"]:
                cls_name = obj["name"]
                if cls_name not in name_to_index:
                    stats["skipped_unknown_class"] += 1
                    continue

                ci = name_to_index[cls_name]
                # 用 XML 中的 size 做归一化
                polygon = bbox_to_polygon4(
                    obj["xmin"], obj["ymin"], obj["xmax"], obj["ymax"],
                    xml_w, xml_h,
                )
                if not polygon:
                    continue

                # bbox 字段（归一化 0~1，便于查询）
                bbox = {
                    "x1": round(obj["xmin"] / xml_w, 6),
                    "y1": round(obj["ymin"] / xml_h, 6),
                    "x2": round(obj["xmax"] / xml_w, 6),
                    "y2": round(obj["ymax"] / xml_h, 6),
                }
                # area 用像素面积
                area = (obj["xmax"] - obj["xmin"]) * (obj["ymax"] - obj["ymin"])

                ann = Annotation(
                    image_id=image.id,
                    class_id=class_index_to_id[ci],
                    polygon=polygon,
                    bbox=bbox,
                    area=area,
                )
                db.add(ann)
                box_count += 1
                stats["total_boxes"] += 1

            if box_count > 0:
                image.status = "labeled"
                stats["with_ann"] += 1
        finally:
            tmp_xml.unlink(missing_ok=True)

    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "task_type": task_type,
        "stats": stats,
    }


# ===========================================================
# 图像分类（Classification）导入
# ===========================================================

@router.post("/cls-xml-scan")
async def scan_cls_xml_classes(files: List[UploadFile] = File(...)):
    """扫描分类 EasyLabel XML，统计每个类别名出现次数"""
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        for f in files:
            if f.filename and f.filename.lower().endswith('.xml'):
                content = await f.read()
                (tmp_dir / f.filename).write_bytes(content)

        from ..services.import_service import scan_xml_classes
        # 复用 voc 扫描器：每张图取所有 <name> 标签（实际分类只有 1 个 name）
        class_counts = scan_xml_classes(str(tmp_dir))
        return {"classes": class_counts}
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


@router.post("/cls-xml-run")
async def import_cls_project_xml(
    project_name: str = Form(...),
    description: str = Form(default=""),
    crop_size: int = Form(default=224),
    class_mapping_json: str = Form(...),  # {"Broken": {"class_index": 0, "color": "#FF0000"}, ...}
    images: List[UploadFile] = File(...),
    xmls: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    分类项目导入：扫描 XML 取每张图的 <name>（第一个 object）作为该图的分类。
    """
    try:
        class_mapping_raw = json.loads(class_mapping_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="class_mapping_json 格式错误")

    if not class_mapping_raw:
        raise HTTPException(status_code=400, detail="至少需要一个类别")

    name_to_index = {}
    class_defs = {}
    for cls_name, info in class_mapping_raw.items():
        try:
            ci = int(info["class_index"])
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"类别 {cls_name} 缺少 class_index")
        name_to_index[cls_name] = ci
        class_defs[ci] = {"name": cls_name, "color": info.get("color", "#FF0000")}

    # 创建项目（task_type='cls'）
    project = Project(
        name=project_name,
        description=description or "图像分类项目",
        task_type="cls",
        resize_h=crop_size,
        resize_w=crop_size,
        crop_size=crop_size,
        overlap=0.0,
    )
    db.add(project)
    db.flush()

    class_index_to_id = {}
    for ci, info in sorted(class_defs.items()):
        dc = DefectClass(
            project_id=project.id,
            class_index=ci,
            name=info["name"],
            color=info["color"],
        )
        db.add(dc)
        db.flush()
        class_index_to_id[ci] = dc.id

    upload_dir = settings.upload_path / str(project.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 建立 XML 索引
    xml_map = {}
    for xf in xmls:
        if xf.filename and xf.filename.lower().endswith('.xml'):
            stem = Path(xf.filename).stem
            xml_map[stem] = xf

    from ..services.import_service import parse_voc_xml
    import tempfile

    stats = {"total": 0, "labeled": 0, "skipped_no_xml": 0, "skipped_unknown_class": 0,
             "skipped_image_decode": 0, "class_distribution": {}}

    for img_file in images:
        if not img_file.filename:
            continue
        ext = Path(img_file.filename).suffix.lower()
        if ext not in SUPPORTED_IMG_EXTS:
            continue

        stats["total"] += 1
        stem = Path(img_file.filename).stem

        img_content = await img_file.read()
        saved_name = f"{uuid.uuid4().hex[:8]}_{img_file.filename}"
        img_saved_path = upload_dir / saved_name
        img_saved_path.write_bytes(img_content)

        import cv2, numpy as np
        img_array = cv2.imdecode(np.frombuffer(img_content, np.uint8), cv2.IMREAD_UNCHANGED)
        if img_array is None:
            stats["skipped_image_decode"] += 1
            img_saved_path.unlink(missing_ok=True)
            continue
        h, w = img_array.shape[:2]

        # 查 XML 取第一个 <name> 作为分类
        xml_file = xml_map.get(stem)
        cls_name = None
        if xml_file:
            xml_content = await xml_file.read()
            await xml_file.seek(0)
            tmp_xml = Path(tempfile.mktemp(suffix='.xml'))
            tmp_xml.write_bytes(xml_content)
            try:
                voc = parse_voc_xml(str(tmp_xml))
                if voc["objects"]:
                    cls_name = voc["objects"][0]["name"]
            finally:
                tmp_xml.unlink(missing_ok=True)

        cls_id = None
        if cls_name and cls_name in name_to_index:
            ci = name_to_index[cls_name]
            cls_id = class_index_to_id[ci]
            stats["labeled"] += 1
            stats["class_distribution"][cls_name] = stats["class_distribution"].get(cls_name, 0) + 1
        else:
            if not xml_file:
                stats["skipped_no_xml"] += 1
            elif cls_name:
                stats["skipped_unknown_class"] += 1

        rel_path = f"{project.id}/{saved_name}"
        image = Image(
            project_id=project.id,
            filename=img_file.filename,
            file_path=rel_path,
            width=w, height=h,
            class_id=cls_id,
            status="labeled" if cls_id else "unlabeled",
        )
        db.add(image)

    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "task_type": "cls",
        "stats": stats,
    }


@router.post("/cls-folder-run")
async def import_cls_project_folder(
    project_name: str = Form(...),
    description: str = Form(default=""),
    crop_size: int = Form(default=224),
    files: List[UploadFile] = File(...),  # 用 webkitdirectory 上传时，每个文件的 filename 是 "类别/xx.bmp"
    db: Session = Depends(get_db),
):
    """
    分类项目导入（文件夹方式）：上传带相对路径的文件，按一级目录名作为类别。

    前端用 webkitdirectory 选目录时，UploadFile 的 filename 会是相对路径
    （例如 "Broken/img1.bmp"，"OK/img2.bmp"）。
    """
    import tempfile, cv2, numpy as np

    # 第一遍：扫描类别
    class_to_count = {}
    file_groups = {}  # cls_name → list of (filename, content)
    for f in files:
        if not f.filename:
            continue
        # 取相对路径的一级目录
        # filename 形如 "Broken/img1.bmp" 或 "Broken\\img1.bmp"
        path_parts = f.filename.replace("\\", "/").split("/")
        if len(path_parts) < 2:
            # 没有目录前缀，跳过
            continue
        cls_name = path_parts[0].strip()
        basename = path_parts[-1]
        ext = Path(basename).suffix.lower()
        if ext not in SUPPORTED_IMG_EXTS:
            continue
        content = await f.read()
        await f.seek(0)
        file_groups.setdefault(cls_name, []).append((basename, content))
        class_to_count[cls_name] = class_to_count.get(cls_name, 0) + 1

    if not class_to_count:
        raise HTTPException(status_code=400, detail="未找到任何按类别归类的图片，请检查目录结构")

    # 创建项目
    project = Project(
        name=project_name,
        description=description or "图像分类项目（文件夹导入）",
        task_type="cls",
        resize_h=crop_size,
        resize_w=crop_size,
        crop_size=crop_size,
        overlap=0.0,
    )
    db.add(project)
    db.flush()

    # 创建类别（按字母序赋 class_index）
    sorted_cls = sorted(class_to_count.keys())
    class_index_to_id = {}
    cls_name_to_id = {}
    default_colors = ['#FF4D4F', '#52C41A', '#1890FF', '#FAAD14', '#722ED1', '#13C2C2', '#EB2F96']
    for i, name in enumerate(sorted_cls):
        dc = DefectClass(
            project_id=project.id,
            class_index=i,
            name=name,
            color=default_colors[i % len(default_colors)],
        )
        db.add(dc)
        db.flush()
        class_index_to_id[i] = dc.id
        cls_name_to_id[name] = dc.id

    upload_dir = settings.upload_path / str(project.id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    stats = {"total": 0, "labeled": 0, "skipped_image_decode": 0,
             "class_distribution": dict(class_to_count)}

    for cls_name, file_list in file_groups.items():
        cls_id = cls_name_to_id[cls_name]
        for basename, content in file_list:
            stats["total"] += 1

            saved_name = f"{uuid.uuid4().hex[:8]}_{basename}"
            img_saved_path = upload_dir / saved_name
            img_saved_path.write_bytes(content)

            img_array = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
            if img_array is None:
                stats["skipped_image_decode"] += 1
                img_saved_path.unlink(missing_ok=True)
                continue
            h, w = img_array.shape[:2]

            rel_path = f"{project.id}/{saved_name}"
            image = Image(
                project_id=project.id,
                filename=basename,
                file_path=rel_path,
                width=w, height=h,
                class_id=cls_id,
                status="labeled",
            )
            db.add(image)
            stats["labeled"] += 1

    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "task_type": "cls",
        "stats": stats,
    }
