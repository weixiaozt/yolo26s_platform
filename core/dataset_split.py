# -*- coding: utf-8 -*-
"""
数据集划分模块 (dataset_split.py)
==================================
功能：将滑窗切割后的子图划分为训练集和验证集，并支持：
    1. 按指定比例划分（默认 8:2）
    2. 稀有类别过采样（通过复制增加稀有类别的样本数）
    3. 背景图（无标注子图）过滤（只随机保留少量到训练集）

输入：
    - 滑窗切割后的 images/ 和 labels/ 文件夹
    - 划分比例、过采样倍数、背景保留比例

输出：
    - dataset/images/train/  dataset/images/val/
    - dataset/labels/train/  dataset/labels/val/
"""

import os
import random
import shutil
from pathlib import Path
from typing import Optional, Callable
from collections import Counter


def parse_label_file(label_path: Path) -> list:
    """
    解析 YOLO 格式的标注文件，返回包含的类别ID列表。

    Args:
        label_path: 标注文件路径

    Returns:
        类别ID列表（可能有重复，表示多个实例）
    """
    classes = []
    if not label_path.exists():
        return classes

    with open(label_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                cls_id = int(line.split()[0])
                classes.append(cls_id)
    return classes


def run_dataset_split(
    cropped_dir: str,
    output_dir: str,
    train_ratio: float = 0.8,
    oversample_factor: int = 5,
    bg_keep_ratio: float = 0.10,
    random_seed: int = 42,
    progress_callback: Optional[Callable] = None
) -> dict:
    """
    执行数据集划分：将子图分为训练集和验证集。

    划分策略：
        1. 将所有子图分为"有标注"和"无标注（背景）"两组
        2. 有标注的子图按 train_ratio 随机划分
        3. 无标注的子图只随机保留 bg_keep_ratio 比例到训练集，不进入验证集
        4. 对训练集中的稀有类别样本进行过采样（复制 oversample_factor 倍）

    Args:
        cropped_dir: 滑窗切割输出目录（包含 images/ 和 labels/ 子文件夹）
        output_dir: 输出目录（会创建 images/{train,val}/ 和 labels/{train,val}/）
        train_ratio: 训练集比例（默认 0.8）
        oversample_factor: 稀有类别过采样倍数（默认 5，设为 1 表示不过采样）
        bg_keep_ratio: 背景图保留比例（默认 0.10，即只保留 10%）
        random_seed: 随机种子（保证可复现）
        progress_callback: 进度回调函数 callback(current, total, message)

    Returns:
        统计信息字典
    """
    random.seed(random_seed)

    cropped_dir = Path(cropped_dir)
    img_dir = cropped_dir / "images"
    lbl_dir = cropped_dir / "labels"

    # ---- 创建输出目录 ----
    output_dir = Path(output_dir)
    for split in ['train', 'val']:
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    # ---- 分类所有子图 ----
    labeled_samples = []    # (stem, [class_ids])  有标注的样本
    background_samples = [] # [stem]  无标注的背景样本

    all_images = sorted(img_dir.glob("*.png"))
    for img_path in all_images:
        stem = img_path.stem
        lbl_path = lbl_dir / f"{stem}.txt"
        classes = parse_label_file(lbl_path)
        if classes:
            labeled_samples.append((stem, classes))
        else:
            background_samples.append(stem)

    # ---- 统计类别分布（用于确定稀有类别）----
    all_class_counts = Counter()
    for stem, classes in labeled_samples:
        all_class_counts.update(classes)

    # 稀有类别：实例数低于中位数的类别
    if all_class_counts:
        median_count = sorted(all_class_counts.values())[len(all_class_counts) // 2]
        rare_classes = {cls for cls, cnt in all_class_counts.items() if cnt <= median_count}
    else:
        rare_classes = set()

    # ---- 划分有标注样本 ----
    random.shuffle(labeled_samples)
    split_idx = int(len(labeled_samples) * train_ratio)
    train_labeled = labeled_samples[:split_idx]
    val_labeled = labeled_samples[split_idx:]

    # ---- 处理背景样本 ----
    random.shuffle(background_samples)
    bg_keep_count = max(1, int(len(background_samples) * bg_keep_ratio))
    train_bg = background_samples[:bg_keep_count]
    # 背景样本不进入验证集

    # ---- 构建最终的训练集和验证集列表 ----
    train_stems = []
    val_stems = []

    # 添加有标注的训练样本
    for stem, classes in train_labeled:
        train_stems.append(stem)
        # 如果包含稀有类别，进行过采样
        if rare_classes and any(c in rare_classes for c in classes):
            for k in range(1, oversample_factor):
                train_stems.append(f"{stem}__oversample_{k}")

    # 添加有标注的验证样本
    for stem, classes in val_labeled:
        val_stems.append(stem)

    # 添加背景训练样本
    for stem in train_bg:
        train_stems.append(stem)

    # ---- 复制文件 ----
    total_ops = len(train_stems) + len(val_stems)
    current_op = 0

    def copy_sample(stem: str, split: str):
        """复制一个样本（图像+标注）到目标目录"""
        nonlocal current_op

        # 处理过采样的文件名
        original_stem = stem.split("__oversample_")[0] if "__oversample_" in stem else stem

        src_img = img_dir / f"{original_stem}.png"
        src_lbl = lbl_dir / f"{original_stem}.txt"
        dst_img = output_dir / "images" / split / f"{stem}.png"
        dst_lbl = output_dir / "labels" / split / f"{stem}.txt"

        if src_img.exists():
            shutil.copy2(str(src_img), str(dst_img))
        if src_lbl.exists():
            shutil.copy2(str(src_lbl), str(dst_lbl))
        else:
            # 无标注文件，创建空文件
            dst_lbl.touch()

        current_op += 1
        if progress_callback:
            progress_callback(current_op, total_ops, f"划分数据集: {stem}")

    # 复制训练集
    for stem in train_stems:
        copy_sample(stem, "train")

    # 复制验证集
    for stem in val_stems:
        copy_sample(stem, "val")

    # ---- 统计信息 ----
    stats = {
        "total_labeled": len(labeled_samples),
        "total_background": len(background_samples),
        "train_labeled": len(train_labeled),
        "train_bg": len(train_bg),
        "train_oversampled": len(train_stems) - len(train_labeled) - len(train_bg),
        "train_total": len(train_stems),
        "val_total": len(val_stems),
        "class_distribution": dict(all_class_counts),
        "rare_classes": list(rare_classes),
        "oversample_factor": oversample_factor,
    }

    return stats
