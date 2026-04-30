# -*- coding: utf-8 -*-
"""
数据集构建服务 (dataset_service.py)
====================================
核心桥接模块：从 MySQL 读取 Web 标注数据，生成 YOLO 格式的训练数据集，
然后调用现有 core/ 模块执行完整的训练流水线。

这是 Web 标注系统和现有训练代码之间最关键的连接层。

数据流：
    MySQL annotations 表
        → 按 image 分组
        → polygon JSON → YOLO polygon TXT
        → 生成 images/ + labels/ 目录
        → 调用 core/preprocess → core/sliding_window → core/dataset_split
        → 输出可直接用于 core/train 的完整数据集
"""

import sys
import shutil
from pathlib import Path
from typing import Optional

# 确保项目根目录在 sys.path 中，以便导入 core/ 模块
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sqlalchemy.orm import Session

from ..config import settings
from ..models.project import Project
from ..models.image import Image
from ..models.annotation import Annotation
from ..models.defect_class import DefectClass


def build_dataset_from_db(
    project_id: int,
    output_dir: str,
    db: Session,
    only_reviewed: bool = False,
) -> dict:
    """
    从 MySQL 读取标注数据，生成原始图像 + YOLO 标注文件。

    这一步产出的目录结构：
        output_dir/
        ├── images/       # 原始图像（复制）
        │   ├── 0001.png
        │   └── 0002.png
        └── masks_yolo/   # YOLO polygon 标注
            ├── 0001.txt
            └── 0002.txt

    后续交给 core/preprocess → core/sliding_window → core/dataset_split 处理。

    Args:
        project_id: 项目ID
        output_dir: 输出目录
        db: 数据库 Session
        only_reviewed: 是否仅使用已审核的图像

    Returns:
        统计信息字典
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"项目不存在: {project_id}")

    # 查询类别映射: defect_class.id → class_index
    class_map = {}
    classes = db.query(DefectClass).filter(DefectClass.project_id == project_id).all()
    for dc in classes:
        class_map[dc.id] = dc.class_index
    class_names = [dc.name for dc in sorted(classes, key=lambda x: x.class_index)]

    # 查询图像（只取已标注/已审核的 + 无标注的背景图）
    status_filter = ["labeled", "reviewed"] if not only_reviewed else ["reviewed"]
    # 有标注的图像 + OK图像
    labeled_images = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.status.in_(status_filter))
        .all()
    )
    # 无标注的图像不参与训练（避免引入未确认的脏数据）
    bg_images = []
    all_images = labeled_images + bg_images

    if not all_images:
        raise ValueError("没有可用的图像数据")

    # 创建输出目录
    out_dir = Path(output_dir)
    img_out = out_dir / "images"
    lbl_out = out_dir / "labels"
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    stats = {
        "total_images": len(all_images),
        "labeled_images": 0,
        "background_images": 0,
        "ok_images": 0,
        "total_annotations": 0,
        "class_names": class_names,
        "class_distribution": {},
        "ok_stems": [],  # OK图像的文件名stem，用于强制加入训练集
    }

    for image in all_images:
        # 复制图像文件（兼容绝对路径和相对路径）
        fp = Path(image.file_path)
        if fp.is_absolute() and fp.exists():
            src_path = fp
        else:
            src_path = settings.upload_path / image.file_path
        if not src_path.exists():
            continue

        # 用 image.id 作为文件名，避免重名
        stem = f"{image.id:06d}"
        dst_img = img_out / f"{stem}.png"
        shutil.copy2(str(src_path), str(dst_img))

        # 查询该图像的所有标注
        annotations = (
            db.query(Annotation)
            .filter(Annotation.image_id == image.id)
            .all()
        )

        # 生成 YOLO polygon 标注文件
        lines = []
        for ann in annotations:
            cls_index = class_map.get(ann.class_id)
            if cls_index is None:
                continue

            polygon = ann.polygon  # [{"x": 0.1, "y": 0.2}, ...] 或 [[39.0, 267.0], ...]
            if len(polygon) < 3:
                continue

            # 兼容两种格式 + 自动归一化
            img_w = image.width or 1
            img_h = image.height or 1
            parts = []
            for p in polygon:
                if isinstance(p, dict):
                    px, py = p['x'], p['y']
                else:
                    px, py = p[0], p[1]
                # 如果坐标 > 1，说明是像素坐标，需要归一化
                if px > 1 or py > 1:
                    px = px / img_w
                    py = py / img_h
                parts.append(f"{px:.6f} {py:.6f}")
            coords = " ".join(parts)
            lines.append(f"{cls_index} {coords}")

            # 统计
            stats["class_distribution"][cls_index] = \
                stats["class_distribution"].get(cls_index, 0) + 1
            stats["total_annotations"] += 1

        # 写标注文件（空标注也写空文件，标识为背景图）
        lbl_path = lbl_out / f"{stem}.txt"
        lbl_path.write_text("\n".join(lines) + ("\n" if lines else ""))

        if lines:
            stats["labeled_images"] += 1
        elif image.status == "reviewed":
            # 显式标记为OK的图像（负样本），需要全部参与训练
            stats["ok_images"] += 1
            stats["ok_stems"].append(stem)
        else:
            stats["background_images"] += 1

    return stats


def build_detection_dataset_from_db(
    project_id: int,
    output_dir: str,
    db: Session,
    only_reviewed: bool = False,
) -> dict:
    """
    目标检测数据集构建：将 polygon (4点矩形) → YOLO det txt (class cx cy w h)

    输出结构：
        output_dir/
        ├── images/   # 原始图像（复制）
        └── labels/   # YOLO det txt（每行: class_id cx cy w h，归一化）

    Args:
        project_id: 项目ID
        output_dir: 输出目录
        db: 数据库 Session
        only_reviewed: 是否仅使用已审核的图像

    Returns:
        统计信息字典
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"项目不存在: {project_id}")

    # 类别映射
    class_map = {}
    classes = db.query(DefectClass).filter(DefectClass.project_id == project_id).all()
    for dc in classes:
        class_map[dc.id] = dc.class_index
    class_names = [dc.name for dc in sorted(classes, key=lambda x: x.class_index)]

    # 查询图像
    status_filter = ["labeled", "reviewed"] if not only_reviewed else ["reviewed"]
    images_q = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.status.in_(status_filter))
        .all()
    )

    if not images_q:
        raise ValueError("没有可用的已标注图像")

    out_dir = Path(output_dir)
    img_out = out_dir / "images"
    lbl_out = out_dir / "labels"
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)

    stats = {
        "total_images": len(images_q),
        "labeled_images": 0,
        "background_images": 0,
        "total_annotations": 0,
        "class_names": class_names,
        "class_distribution": {},
    }

    for image in images_q:
        # 源图路径
        fp = Path(image.file_path)
        if fp.is_absolute() and fp.exists():
            src_path = fp
        else:
            src_path = settings.upload_path / image.file_path
        if not src_path.exists():
            continue

        # 用 image.id 作为 stem 保证唯一
        stem = f"{image.id:06d}"
        # 保留原始扩展名（YOLO 支持 .bmp/.png/.jpg）
        ext = src_path.suffix.lower()
        if ext not in {'.bmp', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}:
            ext = '.png'
        dst_img = img_out / f"{stem}{ext}"
        shutil.copy2(str(src_path), str(dst_img))

        # 读取标注
        annotations = (
            db.query(Annotation)
            .filter(Annotation.image_id == image.id)
            .all()
        )

        img_w = image.width or 1
        img_h = image.height or 1

        lines = []
        for ann in annotations:
            cls_index = class_map.get(ann.class_id)
            if cls_index is None:
                continue

            # 优先用 bbox 字段（更准），否则从 polygon 推算
            x1 = y1 = x2 = y2 = None
            if ann.bbox and isinstance(ann.bbox, dict):
                try:
                    x1 = float(ann.bbox.get("x1"))
                    y1 = float(ann.bbox.get("y1"))
                    x2 = float(ann.bbox.get("x2"))
                    y2 = float(ann.bbox.get("y2"))
                except (TypeError, ValueError):
                    x1 = y1 = x2 = y2 = None

            if x1 is None and ann.polygon:
                xs, ys = [], []
                for p in ann.polygon:
                    if isinstance(p, dict):
                        xs.append(float(p['x']))
                        ys.append(float(p['y']))
                    else:
                        xs.append(float(p[0]))
                        ys.append(float(p[1]))
                if xs and ys:
                    x1, y1 = min(xs), min(ys)
                    x2, y2 = max(xs), max(ys)

            if x1 is None:
                continue

            # 自动判断坐标空间：>1 像素，否则归一化
            if max(x1, y1, x2, y2) > 1.0:
                x1 /= img_w
                y1 /= img_h
                x2 /= img_w
                y2 /= img_h

            # clamp [0, 1]
            x1 = max(0.0, min(1.0, x1))
            y1 = max(0.0, min(1.0, y1))
            x2 = max(0.0, min(1.0, x2))
            y2 = max(0.0, min(1.0, y2))

            bw = x2 - x1
            bh = y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            cx = x1 + bw / 2.0
            cy = y1 + bh / 2.0

            lines.append(f"{cls_index} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            stats["class_distribution"][cls_index] = \
                stats["class_distribution"].get(cls_index, 0) + 1
            stats["total_annotations"] += 1

        lbl_path = lbl_out / f"{stem}.txt"
        lbl_path.write_text("\n".join(lines) + ("\n" if lines else ""))

        if lines:
            stats["labeled_images"] += 1
        else:
            stats["background_images"] += 1

    return stats


def prepare_detection_dataset(
    project_id: int,
    task_output_dir: str,
    db: Session,
    train_ratio: float = 0.85,
    seed: int = 42,
    progress_callback=None,
) -> dict:
    """
    目标检测数据集准备流程（不滑窗）：
        1. build_detection_dataset_from_db() → 原图 + YOLO det txt
        2. 按 train_ratio 划分 train/val
        3. 复制到 dataset/images/{train,val} + dataset/labels/{train,val}
    """
    import random

    task_dir = Path(task_output_dir)

    # ---- 阶段 1: 从数据库导出 ----
    if progress_callback:
        progress_callback(0, 2, "从数据库导出标注数据...")

    raw_dir = str(task_dir / "raw")
    export_stats = build_detection_dataset_from_db(project_id, raw_dir, db)
    class_names = export_stats["class_names"]

    raw_path = Path(raw_dir)
    img_files = sorted((raw_path / "images").iterdir())
    if not img_files:
        raise ValueError("数据集为空")

    # 只保留有对应 label 的图（label 文件总是会被写出，但要保证图存在）
    valid = []
    for f in img_files:
        if f.is_file():
            valid.append(f)

    # ---- 阶段 2: 划分 train/val ----
    if progress_callback:
        progress_callback(1, 2, "划分训练集 / 验证集...")

    random.seed(seed)
    indices = list(range(len(valid)))
    random.shuffle(indices)
    split_idx = max(1, int(len(indices) * train_ratio))
    train_set = set(indices[:split_idx])

    dataset_dir = task_dir / "dataset"
    for split in ("train", "val"):
        (dataset_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    train_count = 0
    val_count = 0
    for i, img_path in enumerate(valid):
        split = "train" if i in train_set else "val"
        if split == "train":
            train_count += 1
        else:
            val_count += 1
        # 复制图
        shutil.copy2(str(img_path), str(dataset_dir / "images" / split / img_path.name))
        # 复制 label（同名 .txt）
        lbl_src = raw_path / "labels" / f"{img_path.stem}.txt"
        if lbl_src.exists():
            shutil.copy2(str(lbl_src), str(dataset_dir / "labels" / split / f"{img_path.stem}.txt"))
        else:
            # 缺标注，写空文件（背景）
            (dataset_dir / "labels" / split / f"{img_path.stem}.txt").touch()

    if progress_callback:
        progress_callback(2, 2, "数据集准备完成")

    return {
        "dataset_dir": str(dataset_dir),
        "class_names": class_names,
        "export_stats": export_stats,
        "split_stats": {"train": train_count, "val": val_count, "total": len(valid)},
    }


def prepare_full_dataset(
    project_id: int,
    task_output_dir: str,
    db: Session,
    target_h: int = 2048,
    target_w: int = 2048,
    crop_size: int = 640,
    overlap: float = 0.2,
    train_ratio: float = 0.8,
    oversample_factor: int = 5,
    bg_keep_ratio: float = 0.1,
    use_morphology: bool = True,
    dilate_kernel: int = 3,
    erode_kernel: int = 3,
    mask_dilate_kernel: int = 0,
    progress_callback=None,
) -> dict:
    """
    完整数据集准备流程：从数据库标注 → 训练就绪的数据集。

    调用顺序：
        1. build_dataset_from_db() → 原始图像 + YOLO 标注
        2. core/preprocess.run_preprocess() → Resize
        3. core/sliding_window.run_sliding_window() → 滑窗切割
        4. core/dataset_split.run_dataset_split() → 训练/验证划分

    Args:
        project_id: 项目ID
        task_output_dir: 任务输出根目录
        db: 数据库 Session
        其余参数: 与现有 core/ 模块参数对齐

    Returns:
        包含 dataset_dir 和 class_names 的字典
    """
    task_dir = Path(task_output_dir)

    # 确保 core/ 可导入
    import sys as _sys
    _root = str(Path(__file__).parent.parent.parent)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)

    # ---- 阶段 1: 从数据库导出 ----
    if progress_callback:
        progress_callback(0, 4, "从数据库导出标注数据...")

    raw_dir = str(task_dir / "raw")
    export_stats = build_dataset_from_db(project_id, raw_dir, db)
    class_names = export_stats["class_names"]

    raw_img_dir = str(Path(raw_dir) / "images")
    raw_lbl_dir = str(Path(raw_dir) / "labels")

    # ---- 阶段 2: 预处理 Resize ----
    if progress_callback:
        progress_callback(1, 4, "预处理 Resize + 形态学处理...")

    from core.preprocess import run_preprocess
    resized_dir = str(task_dir / "resized")
    run_preprocess(
        image_dir=raw_img_dir,
        mask_dir=raw_lbl_dir,
        output_dir=resized_dir,
        target_h=target_h,
        target_w=target_w,
        dilate_kernel=dilate_kernel,
        erode_kernel=erode_kernel,
        use_morphology=use_morphology,
        mask_dilate_kernel=mask_dilate_kernel,
    )

    # 注意：preprocess 是为 mask 格式设计的，但我们的标注是 YOLO TXT 格式。
    # 对于 YOLO polygon 标注（归一化坐标），Resize 不影响标注坐标。
    # 所以我们只 Resize 图像，标注文件直接复制过去。
    resized_img_dir = str(Path(resized_dir) / "images")

    # 将 YOLO 标注文件复制到 resized 目录旁边
    # sliding_window 需要的是 mask 格式，但我们的标注已经是 YOLO 格式
    # 所以这里跳过 sliding_window 的 mask→YOLO 转换，直接构建数据集

    # ---- 阶段 2b: 直接用 YOLO 标注构建滑窗数据集 ----
    # 如果 resize 后图像 == crop_size，不需要滑窗
    if target_h == crop_size and target_w == crop_size:
        # 不需要滑窗，直接用 raw 的 images + labels
        cropped_dir = raw_dir
    else:
        # 需要滑窗切割图像，并对应裁剪标注
        if progress_callback:
            progress_callback(2, 4, "滑窗切割...")
        cropped_dir = str(task_dir / "cropped")
        _sliding_window_with_yolo_labels(
            image_dir=resized_img_dir,
            label_dir=raw_lbl_dir,
            output_dir=cropped_dir,
            crop_size=crop_size,
            overlap=overlap,
            img_h=target_h,
            img_w=target_w,
        )

    # ---- 阶段 3: 数据集划分 ----
    if progress_callback:
        progress_callback(3, 4, "数据集划分...")

    from core.dataset_split import run_dataset_split
    dataset_dir = str(task_dir / "dataset")
    split_stats = run_dataset_split(
        cropped_dir=cropped_dir,
        output_dir=dataset_dir,
        train_ratio=train_ratio,
        oversample_factor=oversample_factor,
        bg_keep_ratio=bg_keep_ratio,
    )

    # ---- 强制将 OK 图像（负样本）全部加入训练集 ----
    # dataset_split 可能只保留了 bg_keep_ratio 比例的背景图，
    # 但用户显式标记为 OK 的图像必须全部参与训练
    ok_stems = export_stats.get("ok_stems", [])
    if ok_stems:
        import shutil as _shutil
        ds_path = Path(dataset_dir)
        cropped_path = Path(cropped_dir)
        ok_added = 0
        for stem in ok_stems:
            # OK 图像经过滑窗后可能有多个子图，匹配所有以该 stem 开头的文件
            for img_file in (cropped_path / "images").glob(f"{stem}*.png"):
                dst_img = ds_path / "images" / "train" / img_file.name
                dst_lbl = ds_path / "labels" / "train" / f"{img_file.stem}.txt"
                if not dst_img.exists():
                    _shutil.copy2(str(img_file), str(dst_img))
                    # 空标注文件（负样本）
                    lbl_src = cropped_path / "labels" / f"{img_file.stem}.txt"
                    if lbl_src.exists():
                        _shutil.copy2(str(lbl_src), str(dst_lbl))
                    else:
                        dst_lbl.touch()
                    ok_added += 1
        split_stats["ok_force_added"] = ok_added

    if progress_callback:
        progress_callback(4, 4, "数据集准备完成")

    return {
        "dataset_dir": dataset_dir,
        "class_names": class_names,
        "export_stats": export_stats,
        "split_stats": split_stats,
    }


def _sliding_window_with_yolo_labels(
    image_dir: str,
    label_dir: str,
    output_dir: str,
    crop_size: int,
    overlap: float,
    img_h: int,
    img_w: int,
):
    """
    对已有 YOLO polygon 标注的图像进行滑窗切割（多线程加速）。
    """
    import cv2
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from core.sliding_window import compute_window_positions

    img_dir = Path(image_dir)
    lbl_dir = Path(label_dir)
    out_img = Path(output_dir) / "images"
    out_lbl = Path(output_dir) / "labels"
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)

    img_files = sorted(img_dir.glob("*.png"))
    if not img_files:
        return

    def process_one_image(img_path):
        """处理单张图片的滑窗切割"""
        img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return 0
        h, w = img.shape[:2]

        # 读取 YOLO 标注
        lbl_path = lbl_dir / f"{img_path.stem}.txt"
        annotations = []
        if lbl_path.exists():
            for line in lbl_path.read_text().strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                cls_id = int(parts[0])
                coords = list(map(float, parts[1:]))
                points = []
                for i in range(0, len(coords), 2):
                    points.append((coords[i] * w, coords[i + 1] * h))
                annotations.append((cls_id, points))

        y_positions = compute_window_positions(h, crop_size, overlap)
        x_positions = compute_window_positions(w, crop_size, overlap)
        count = 0

        for y_start in y_positions:
            for x_start in x_positions:
                crop = img[y_start:y_start + crop_size, x_start:x_start + crop_size]
                if crop.shape[0] != crop_size or crop.shape[1] != crop_size:
                    padded = np.zeros((crop_size, crop_size) + crop.shape[2:], dtype=crop.dtype)
                    padded[:crop.shape[0], :crop.shape[1]] = crop
                    crop = padded

                crop_name = f"{img_path.stem}_{y_start:04d}_{x_start:04d}"
                cv2.imwrite(str(out_img / f"{crop_name}.png"), crop)

                crop_lines = []
                for cls_id, points in annotations:
                    local_points = []
                    for px, py in points:
                        lx = max(0.0, min(px - x_start, crop_size))
                        ly = max(0.0, min(py - y_start, crop_size))
                        local_points.append((lx, ly))

                    inside = any(0 < lx < crop_size and 0 < ly < crop_size for lx, ly in local_points)
                    if not inside:
                        continue
                    if len(local_points) < 3:
                        continue
                    pts_array = np.array(local_points, dtype=np.float32)
                    area = cv2.contourArea(pts_array)
                    if area < 25:
                        continue

                    coords_str = " ".join(f"{lx / crop_size:.6f} {ly / crop_size:.6f}" for lx, ly in local_points)
                    crop_lines.append(f"{cls_id} {coords_str}")

                lbl_out_path = out_lbl / f"{crop_name}.txt"
                lbl_out_path.write_text("\n".join(crop_lines) + ("\n" if crop_lines else ""))
                count += 1

        return count

    # 多线程并行处理所有图像（I/O 密集型，线程池效果好）
    import os
    max_workers = min(os.cpu_count() or 4, len(img_files), 8)
    total_crops = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_one_image, p): p for p in img_files}
        for future in as_completed(futures):
            try:
                total_crops += future.result()
            except Exception as e:
                print(f"[滑窗错误] {futures[future].name}: {e}")
