# -*- coding: utf-8 -*-
"""
数据预处理模块 (preprocess.py)
==============================
功能：将原始大尺寸图像和对应的 Mask 标注统一 Resize 到用户指定的目标尺寸。
- 图像使用 Bicubic 插值（保留细节，适合工业检测场景）
- Mask 使用最近邻插值（保证类别标签不被插值污染）
- 支持形态学处理：生成原图、膨胀图、腐蚀图三通道组合

输入：
    - 原始图像文件夹（支持 .bmp / .png / .jpg / .tif）
    - 原始 Mask 文件夹（PNG, 像素值为类别ID）
    - 目标尺寸 (target_h, target_w)，最小 640x640
    - 形态学参数 (dilate_kernel, erode_kernel)

输出：
    - Resize 后的图像保存到 temp/resized/images/（三通道图）
    - Resize 后的 Mask 保存到 temp/resized/masks/
"""

import os
import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Optional, Callable


def create_morphology_triple_channel(
    image: np.ndarray,
    dilate_kernel: int = 3,
    erode_kernel: int = 3
) -> np.ndarray:
    """
    将单通道灰度图像处理成三通道图：
    - B通道：原图
    - G通道：膨胀图
    - R通道：腐蚀图
    
    Args:
        image: 输入图像 (H, W) 或 (H, W, C)
        dilate_kernel: 膨胀核大小（矩形，奇数）
        erode_kernel: 腐蚀核大小（矩形，奇数）
    
    Returns:
        三通道图像 (H, W, 3)，uint8
    """
    # 确保是灰度图
    if len(image.shape) == 3 and image.shape[2] >= 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif len(image.shape) == 3 and image.shape[2] == 1:
        gray = image[:, :, 0]
    else:
        gray = image.copy()
    
    # 确保核大小为奇数
    dilate_k = dilate_kernel if dilate_kernel % 2 == 1 else dilate_kernel + 1
    erode_k = erode_kernel if erode_kernel % 2 == 1 else erode_kernel + 1
    
    # 形态学处理
    if dilate_k > 0:
        kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_k, dilate_k))
        dilated = cv2.dilate(gray, kernel_dilate, iterations=1)
    else:
        dilated = gray
    
    if erode_k > 0:
        kernel_erode = cv2.getStructuringElement(cv2.MORPH_RECT, (erode_k, erode_k))
        eroded = cv2.erode(gray, kernel_erode, iterations=1)
    else:
        eroded = gray
    
    # 构建三通道图: B=原图, G=膨胀, R=腐蚀
    triple = np.stack([gray, dilated, eroded], axis=2)
    
    return triple


# ============================================================
# 支持的图像格式
# ============================================================
SUPPORTED_IMAGE_EXTS = {'.bmp', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}


def get_image_files(folder: str) -> list:
    """
    获取文件夹中所有支持格式的图像文件路径，按文件名排序。

    Args:
        folder: 图像文件夹路径

    Returns:
        排序后的图像文件 Path 对象列表
    """
    folder = Path(folder)
    files = [
        f for f in sorted(folder.iterdir())
        if f.suffix.lower() in SUPPORTED_IMAGE_EXTS
    ]
    return files


def resize_image(image: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
    """
    使用 Bicubic 插值对图像进行 Resize。

    Args:
        image: 输入图像 (H, W) 或 (H, W, C)
        target_size: 目标尺寸 (height, width)

    Returns:
        Resize 后的图像
    """
    h, w = target_size
    resized = cv2.resize(image, (w, h), interpolation=cv2.INTER_CUBIC)
    return resized


def resize_mask(mask: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
    """
    使用最近邻插值对 Mask 进行 Resize（保证类别标签不被插值污染）。

    Args:
        mask: 输入 Mask (H, W)，像素值为类别ID
        target_size: 目标尺寸 (height, width)

    Returns:
        Resize 后的 Mask
    """
    h, w = target_size
    resized = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    return resized


def dilate_mask(mask: np.ndarray, kernel_size: int) -> np.ndarray:
    """
    对 Mask 标注进行形态学膨胀（按类别单独膨胀，避免类别混合）。
    
    Args:
        mask: 输入 Mask (H, W)，像素值为类别ID
        kernel_size: 膨胀核大小（矩形，奇数）
    
    Returns:
        膨胀后的 Mask
    """
    if kernel_size <= 0:
        return mask
    
    # 确保核大小为奇数
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    
    # 对每个类别单独膨胀，避免类别间混合
    dilated_mask = np.zeros_like(mask)
    for cls_val in np.unique(mask):
        if cls_val > 0:
            binary = (mask == cls_val).astype(np.uint8)
            dilated_binary = cv2.dilate(binary, kernel, iterations=1)
            dilated_mask[dilated_binary > 0] = cls_val
    
    return dilated_mask


def find_matching_mask(image_path: Path, mask_folder: Path) -> Optional[Path]:
    """
    根据图像文件名在 Mask 文件夹中查找对应的 Mask 文件。
    匹配规则：文件名主干（stem）相同，扩展名可以不同。

    Args:
        image_path: 图像文件路径
        mask_folder: Mask 文件夹路径

    Returns:
        匹配到的 Mask 文件路径，未找到则返回 None
    """
    stem = image_path.stem
    for ext in ['.png', '.bmp', '.tif', '.tiff']:
        candidate = mask_folder / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def run_preprocess(
    image_dir: str,
    mask_dir: str,
    output_dir: str,
    target_h: int = 2048,
    target_w: int = 2048,
    dilate_kernel: int = 3,
    erode_kernel: int = 3,
    use_morphology: bool = True,
    mask_dilate_kernel: int = 0,
    progress_callback: Optional[Callable] = None
) -> dict:
    """
    执行数据预处理：将所有图像和 Mask 统一 Resize 到目标尺寸。

    Args:
        image_dir: 原始图像文件夹路径
        mask_dir: 原始 Mask 文件夹路径
        output_dir: 输出根目录（会在其下创建 images/ 和 masks/ 子文件夹）
        target_h: 目标高度（最小 640）
        target_w: 目标宽度（最小 640）
        dilate_kernel: 图像膨胀核大小（矩形，奇数，默认3）
        erode_kernel: 图像腐蚀核大小（矩形，奇数，默认3）
        use_morphology: 是否使用形态学三通道处理
        mask_dilate_kernel: 标注 Mask 膨胀核大小（矩形，奇数，0表示不膨胀，在Resize前进行）
        progress_callback: 进度回调函数 callback(current, total, message)

    Returns:
        统计信息字典：
        {
            "total_images": int,        # 总图像数
            "with_mask": int,           # 有对应 Mask 的图像数
            "without_mask": int,        # 无 Mask 的图像数（纯背景）
            "original_size": (H, W),    # 原始图像尺寸
            "target_size": (H, W),      # 目标尺寸
        }
    """
    # ---- 参数校验 ----
    assert target_h >= 640, f"目标高度不能小于640，当前值: {target_h}"
    assert target_w >= 640, f"目标宽度不能小于640，当前值: {target_w}"

    image_dir = Path(image_dir)
    mask_dir = Path(mask_dir)
    out_img_dir = Path(output_dir) / "images"
    out_mask_dir = Path(output_dir) / "masks"
    out_img_dir.mkdir(parents=True, exist_ok=True)
    out_mask_dir.mkdir(parents=True, exist_ok=True)

    # ---- 获取所有图像文件 ----
    image_files = get_image_files(image_dir)
    total = len(image_files)
    assert total > 0, f"图像文件夹为空: {image_dir}"

    # ---- 统计变量 ----
    stats = {
        "total_images": total,
        "with_mask": 0,
        "without_mask": 0,
        "original_size": None,
        "target_size": (target_h, target_w),
    }

    # ---- 逐张处理 ----
    for i, img_path in enumerate(image_files):
        # 读取图像（支持灰度和彩色）
        img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"[警告] 无法读取图像，跳过: {img_path}")
            continue

        # 记录原始尺寸（取第一张）
        if stats["original_size"] is None:
            stats["original_size"] = (img.shape[0], img.shape[1])

        # 判断是否需要 Resize（如果原图已经是目标尺寸则跳过）
        need_resize = (img.shape[0] != target_h) or (img.shape[1] != target_w)
        
        # 形态学处理：生成三通道图（在Resize前进行，保持原始图像细节）
        if use_morphology:
            img = create_morphology_triple_channel(img, dilate_kernel, erode_kernel)

        # Resize 图像（Bicubic）
        if need_resize:
            img_resized = resize_image(img, (target_h, target_w))
        else:
            img_resized = img

        # 保存 Resize 后的图像（统一保存为 PNG）
        out_img_path = out_img_dir / f"{img_path.stem}.png"
        cv2.imwrite(str(out_img_path), img_resized)

        # 查找并处理对应的 Mask
        mask_path = find_matching_mask(img_path, mask_dir)
        if mask_path is not None:
            # 读取 Mask（保持原始数据类型，可能是 uint8 或 uint16）
            mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
            if mask is not None:
                # 先在原始尺寸上进行标注膨胀（Resize前）
                if mask_dilate_kernel > 0:
                    mask = dilate_mask(mask, mask_dilate_kernel)
                
                # Resize Mask（最近邻）
                if need_resize:
                    mask_resized = resize_mask(mask, (target_h, target_w))
                else:
                    mask_resized = mask

                # 保存 Resize 后的 Mask
                out_mask_path = out_mask_dir / f"{img_path.stem}.png"
                cv2.imwrite(str(out_mask_path), mask_resized)
                stats["with_mask"] += 1
            else:
                print(f"[警告] 无法读取 Mask，跳过: {mask_path}")
                stats["without_mask"] += 1
        else:
            # 没有对应 Mask，说明是无缺陷的背景图
            stats["without_mask"] += 1

        # 进度回调
        if progress_callback:
            progress_callback(i + 1, total, f"预处理: {img_path.name}")

    return stats
