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

import shutil
from pathlib import Path
from typing import Optional

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
    # 无标注的图像（未处理的，作为额外背景图）
    bg_images = (
        db.query(Image)
        .filter(Image.project_id == project_id, Image.status == "unlabeled")
        .all()
    )
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
        # 复制图像文件
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

            polygon = ann.polygon  # [{"x": 0.1, "y": 0.2}, ...]
            if len(polygon) < 3:
                continue

            coords = " ".join(f"{p['x']:.6f} {p['y']:.6f}" for p in polygon)
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
        progress_callback(1, 4, "预处理 Resize...")

    # 判断是否需要 Resize（如果标注时图像已经是目标尺寸则跳过）
    # 这里我们仍然执行 Resize，保证输出统一尺寸
    from core.preprocess import run_preprocess
    resized_dir = str(task_dir / "resized")
    run_preprocess(
        image_dir=raw_img_dir,
        mask_dir=raw_lbl_dir,  # preprocess 只处理图像和 mask，标注文件不经过这里
        output_dir=resized_dir,
        target_h=target_h,
        target_w=target_w,
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
    对已有 YOLO polygon 标注的图像进行滑窗切割。

    与 core/sliding_window.py 不同的是：
    - 输入标注是 YOLO TXT 格式（归一化坐标），不是 mask PNG
    - 需要将归一化坐标转换到切割子图的局部坐标系

    Args:
        image_dir: Resize 后的图像目录
        label_dir: YOLO 标注目录
        output_dir: 输出目录
        crop_size: 切割尺寸
        overlap: 重叠率
        img_h, img_w: 原图尺寸（用于反归一化）
    """
    import cv2
    import numpy as np

    from core.sliding_window import compute_window_positions

    img_dir = Path(image_dir)
    lbl_dir = Path(label_dir)
    out_img = Path(output_dir) / "images"
    out_lbl = Path(output_dir) / "labels"
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)

    for img_path in sorted(img_dir.glob("*.png")):
        img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
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
                # 将归一化坐标转为像素坐标
                points = []
                for i in range(0, len(coords), 2):
                    px = coords[i] * w
                    py = coords[i + 1] * h
                    points.append((px, py))
                annotations.append((cls_id, points))

        # 计算滑窗位置
        y_positions = compute_window_positions(h, crop_size, overlap)
        x_positions = compute_window_positions(w, crop_size, overlap)

        for y_start in y_positions:
            for x_start in x_positions:
                # 裁剪图像
                crop = img[y_start:y_start + crop_size, x_start:x_start + crop_size]
                if crop.shape[0] != crop_size or crop.shape[1] != crop_size:
                    padded = np.zeros((crop_size, crop_size) + crop.shape[2:], dtype=crop.dtype)
                    padded[:crop.shape[0], :crop.shape[1]] = crop
                    crop = padded

                crop_name = f"{img_path.stem}_{y_start:04d}_{x_start:04d}"
                cv2.imwrite(str(out_img / f"{crop_name}.png"), crop)

                # 裁剪标注：将落在当前窗口内的多边形转换为局部归一化坐标
                crop_lines = []
                for cls_id, points in annotations:
                    # 将点转换到 crop 局部坐标
                    local_points = []
                    for px, py in points:
                        lx = px - x_start
                        ly = py - y_start
                        # 裁剪到 [0, crop_size]
                        lx = max(0.0, min(lx, crop_size))
                        ly = max(0.0, min(ly, crop_size))
                        local_points.append((lx, ly))

                    # 检查多边形是否有足够面积落在窗口内
                    # 简单判断：至少有一个点在窗口内部（非边缘）
                    inside = any(
                        0 < lx < crop_size and 0 < ly < crop_size
                        for lx, ly in local_points
                    )
                    if not inside:
                        continue

                    # 计算裁剪后多边形面积
                    if len(local_points) < 3:
                        continue
                    pts_array = np.array(local_points, dtype=np.float32)
                    area = cv2.contourArea(pts_array)
                    if area < 25:  # 与 core/sliding_window.py 一致
                        continue

                    # 归一化到 [0, 1]
                    coords_str = " ".join(
                        f"{lx / crop_size:.6f} {ly / crop_size:.6f}"
                        for lx, ly in local_points
                    )
                    crop_lines.append(f"{cls_id} {coords_str}")

                lbl_out_path = out_lbl / f"{crop_name}.txt"
                lbl_out_path.write_text(
                    "\n".join(crop_lines) + ("\n" if crop_lines else "")
                )
