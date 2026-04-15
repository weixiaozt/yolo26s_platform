# -*- coding: utf-8 -*-
"""
滑窗切割模块 (sliding_window.py)
=================================
功能：将预处理后的图像和 Mask 使用滑动窗口切割为 640x640 的子图，
      并将 Mask 标注转换为 YOLO 实例分割所需的 polygon 格式。

核心逻辑：
    1. 如果图像恰好等于 crop_size（如 640x640），则不滑窗，直接处理。
    2. 如果图像大于 crop_size，则按照指定的重叠率进行滑窗切割。
    3. 对每个子图中的 Mask，提取每个类别的连通区域轮廓，
       转换为 YOLO polygon 格式（归一化坐标）。
    4. 没有任何标注的子图（纯背景）也会被保存，后续由 dataset_split 模块处理。

输出格式（YOLO polygon）：
    每行: class_id x1 y1 x2 y2 ... xn yn
    坐标归一化到 [0, 1]
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Callable


def compute_window_positions(image_size: int, crop_size: int, overlap: float) -> List[int]:
    """
    计算滑窗在某个维度上的所有起始位置。

    Args:
        image_size: 图像在该维度上的尺寸
        crop_size: 滑窗尺寸
        overlap: 重叠率 (0.0 ~ 0.5)

    Returns:
        起始位置列表
    """
    # 如果图像尺寸等于或小于滑窗尺寸，只有一个窗口
    if image_size <= crop_size:
        return [0]

    # 计算步长
    stride = int(crop_size * (1.0 - overlap))
    stride = max(stride, 1)  # 防止步长为0

    positions = []
    pos = 0
    while pos + crop_size <= image_size:
        positions.append(pos)
        pos += stride

    # 确保最后一个窗口覆盖到图像边缘
    if positions[-1] + crop_size < image_size:
        positions.append(image_size - crop_size)

    return positions


def mask_to_yolo_polygons(mask_crop: np.ndarray, crop_size: int) -> List[str]:
    """
    将一个 Mask 子图转换为 YOLO polygon 格式的标注行列表。

    处理流程：
        1. 遍历 Mask 中所有非零类别值
        2. 对每个类别，提取二值化后的连通区域轮廓
        3. 将轮廓点坐标归一化到 [0, 1]
        4. 过滤掉面积过小的噪声区域（< 25 像素）

    Args:
        mask_crop: 裁剪后的 Mask 子图 (H, W)，像素值为类别ID
        crop_size: 子图尺寸（用于归一化）

    Returns:
        YOLO 格式标注行列表，每行: "class_id x1 y1 x2 y2 ... xn yn"
    """
    lines = []
    # 获取所有非零类别
    unique_classes = np.unique(mask_crop)
    unique_classes = unique_classes[unique_classes > 0]  # 排除背景(0)

    for cls_val in unique_classes:
        # 类别ID从0开始（Mask中的值从1开始）
        cls_id = int(cls_val) - 1

        # 提取该类别的二值 Mask
        binary = (mask_crop == cls_val).astype(np.uint8)

        # 查找轮廓
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            # 过滤面积过小的噪声区域
            area = cv2.contourArea(contour)
            if area < 25:
                continue

            # 过滤点数过少的轮廓（至少需要3个点构成多边形）
            if len(contour) < 3:
                continue

            # 简化轮廓点数（减少标注文件大小，加速训练）
            # epsilon 设为周长的 1%，在精度和效率之间取平衡
            epsilon = 0.01 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)

            if len(approx) < 3:
                continue

            # 归一化坐标到 [0, 1]
            points = approx.reshape(-1, 2).astype(float)
            points[:, 0] /= crop_size  # x / width
            points[:, 1] /= crop_size  # y / height

            # 裁剪到 [0, 1] 范围
            points = np.clip(points, 0.0, 1.0)

            # 构建 YOLO 格式行: class_id x1 y1 x2 y2 ...
            coords_str = " ".join(f"{x:.6f} {y:.6f}" for x, y in points)
            line = f"{cls_id} {coords_str}"
            lines.append(line)

    return lines


def run_sliding_window(
    image_dir: str,
    mask_dir: str,
    output_dir: str,
    crop_size: int = 640,
    overlap: float = 0.2,
    progress_callback: Optional[Callable] = None
) -> dict:
    """
    执行滑窗切割：将所有图像和 Mask 切割为子图，并生成 YOLO polygon 标注。

    Args:
        image_dir: 预处理后的图像文件夹路径
        mask_dir: 预处理后的 Mask 文件夹路径
        output_dir: 输出根目录（会在其下创建 images/ 和 labels/ 子文件夹）
        crop_size: 滑窗尺寸（默认 640）
        overlap: 重叠率（默认 0.2，即 20%）
        progress_callback: 进度回调函数 callback(current, total, message)

    Returns:
        统计信息字典：
        {
            "total_crops": int,           # 总子图数
            "crops_with_label": int,      # 有标注的子图数
            "crops_empty": int,           # 无标注的子图数（纯背景）
            "class_instance_count": dict, # 各类别实例数 {cls_id: count}
            "no_sliding": bool,           # 是否跳过了滑窗（图像=crop_size）
        }
    """
    image_dir = Path(image_dir)
    mask_dir = Path(mask_dir)
    out_img_dir = Path(output_dir) / "images"
    out_lbl_dir = Path(output_dir) / "labels"
    out_img_dir.mkdir(parents=True, exist_ok=True)
    out_lbl_dir.mkdir(parents=True, exist_ok=True)

    # ---- 获取所有图像 ----
    from .preprocess import get_image_files
    image_files = get_image_files(image_dir)
    total = len(image_files)
    assert total > 0, f"图像文件夹为空: {image_dir}"

    # ---- 统计变量 ----
    stats = {
        "total_crops": 0,
        "crops_with_label": 0,
        "crops_empty": 0,
        "class_instance_count": {},
        "no_sliding": False,
    }

    crop_idx = 0  # 全局子图编号

    for file_i, img_path in enumerate(image_files):
        # 读取图像
        img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        h, w = img.shape[:2]

        # 查找对应 Mask（可能没有）
        mask_path = mask_dir / f"{img_path.stem}.png"
        mask = None
        if mask_path.exists():
            mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)

        # ---- 判断是否需要滑窗 ----
        if h == crop_size and w == crop_size:
            # 图像恰好等于 crop_size，不滑窗，直接处理
            stats["no_sliding"] = True
            windows = [(0, 0)]
        else:
            # 计算滑窗位置
            y_positions = compute_window_positions(h, crop_size, overlap)
            x_positions = compute_window_positions(w, crop_size, overlap)
            windows = [(y, x) for y in y_positions for x in x_positions]

        # ---- 逐窗口切割 ----
        for (y_start, x_start) in windows:
            # 裁剪图像
            img_crop = img[y_start:y_start + crop_size, x_start:x_start + crop_size]

            # 确保裁剪尺寸正确（边缘可能不足）
            if img_crop.shape[0] != crop_size or img_crop.shape[1] != crop_size:
                # 用零填充到 crop_size
                padded = np.zeros((crop_size, crop_size) + img_crop.shape[2:], dtype=img_crop.dtype)
                padded[:img_crop.shape[0], :img_crop.shape[1]] = img_crop
                img_crop = padded

            # 生成子图文件名: 原图名_行_列
            crop_name = f"{img_path.stem}_{y_start:04d}_{x_start:04d}"

            # 保存子图
            cv2.imwrite(str(out_img_dir / f"{crop_name}.png"), img_crop)

            # 处理 Mask 标注
            label_lines = []
            if mask is not None:
                mask_crop = mask[y_start:y_start + crop_size, x_start:x_start + crop_size]
                if mask_crop.shape[0] != crop_size or mask_crop.shape[1] != crop_size:
                    padded_mask = np.zeros((crop_size, crop_size), dtype=mask_crop.dtype)
                    padded_mask[:mask_crop.shape[0], :mask_crop.shape[1]] = mask_crop
                    mask_crop = padded_mask

                label_lines = mask_to_yolo_polygons(mask_crop, crop_size)

            # 保存标注文件（即使为空也保存，方便后续统计）
            lbl_path = out_lbl_dir / f"{crop_name}.txt"
            with open(lbl_path, 'w') as f:
                f.write("\n".join(label_lines) + "\n" if label_lines else "")

            # 统计
            stats["total_crops"] += 1
            if label_lines:
                stats["crops_with_label"] += 1
                # 统计各类别实例数
                for line in label_lines:
                    cls_id = int(line.split()[0])
                    stats["class_instance_count"][cls_id] = \
                        stats["class_instance_count"].get(cls_id, 0) + 1
            else:
                stats["crops_empty"] += 1

            crop_idx += 1

        # 进度回调
        if progress_callback:
            progress_callback(file_i + 1, total, f"滑窗切割: {img_path.name}")

    return stats
