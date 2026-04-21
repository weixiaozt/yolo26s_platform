# -*- coding: utf-8 -*-
"""
推断模块 (inference.py)
========================
功能：使用训练好的 YOLO26s-seg 模型对大尺寸图像进行滑窗推断，
      并将各子图的检测结果合并到原图坐标系下。

核心流程：
    1. 对原图进行边缘 Padding（防止边缘缺陷被截断）
    2. 计算滑窗位置
    3. 逐窗口推断
    4. 将所有子图的检测结果（Box + Mask）映射回原图坐标
    5. 对合并后的结果执行 NMS 去重
    6. 生成可视化叠加图和分割 Mask 图

输入：
    - 模型路径（.pt / .onnx / OpenVINO .xml）
    - 单张图像路径
    - 推断参数（置信度、IoU、滑窗参数等）

输出：
    - 检测结果列表（Box + Mask + Class + Confidence）
    - 可视化叠加图
    - 分割 Mask 图
    - 检测时间
"""

import time

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict


# ============================================================
# 颜色映射表（用于可视化不同类别的 Mask）
# ============================================================
CLASS_COLORS = [
    (255, 0, 0),     # 类别0: 红色
    (0, 255, 0),     # 类别1: 绿色
    (0, 0, 255),     # 类别2: 蓝色
    (255, 255, 0),   # 类别3: 黄色
    (255, 0, 255),   # 类别4: 品红
    (0, 255, 255),   # 类别5: 青色
]


def load_model(model_path: str, model_type: str = "auto", device: str = None):
    """
    加载 YOLO 模型。支持 .pt / .onnx / OpenVINO .xml / TensorRT .engine 格式。

    Args:
        model_path: 模型文件路径
        model_type: 模型类型 ("pytorch", "openvino", "tensorrt", "auto" 自动识别)
        device: 推断设备（OpenVINO/TensorRT 时有效）

    Returns:
        加载好的 YOLO 模型对象，以及模型类型信息
    """
    from ultralytics import YOLO
    from pathlib import Path
    
    model_path = Path(model_path)
    
    # 自动识别模型类型
    if model_type == "auto":
        suffix = model_path.suffix.lower()
        if suffix == '.xml':
            model_type = "openvino"
        elif suffix == '.engine':
            model_type = "tensorrt"
        elif suffix in ['.pt', '.pth']:
            model_type = "pytorch"
        else:
            model_type = "pytorch"  # 默认
    
    # OpenVINO 模型: 传入 .xml 文件时，使用模型目录
    if model_type == "openvino":
        # OpenVINO 2026+ 兼容修复
        try:
            import sys as _sys, openvino as _ov
            if 'openvino.runtime' not in _sys.modules:
                _sys.modules['openvino.runtime'] = _ov
        except ImportError:
            pass
        # Ultralytics 需要加载模型目录（包含 .xml 和 .bin），不是 .xml 文件本身
        model_dir = model_path.parent
        model = YOLO(str(model_dir))
        model._model_type = "openvino"
        # 保存设备信息供后续使用，但不通过 predict 传递 device 参数
        model._ov_device = _format_openvino_device(device) if device else None
    # TensorRT 模型
    elif model_type == "tensorrt":
        model = YOLO(str(model_path))
        model._model_type = "tensorrt"
    # PyTorch 模型
    else:
        model = YOLO(str(model_path))
        model._model_type = "pytorch"
        if device:
            model.to(device)
    
    return model, model_type


def _format_openvino_device(device: str) -> str:
    """
    将设备名称格式化为 OpenVINO 格式。
    
    Args:
        device: 设备名称，如 'CPU', 'GPU.0', 'NPU' 等
        
    Returns:
        OpenVINO 格式的设备字符串
    """
    if not device:
        return "AUTO"
    
    device = device.upper()
    
    device_map = {
        'AUTO': 'AUTO',
        'CPU': 'CPU',
        'GPU': 'GPU',
        'GPU.0': 'GPU.0',
        'GPU.1': 'GPU.1',
        'IGPU': 'GPU.0',
        'DGPU': 'GPU.1',
        'NPU': 'NPU',
    }
    
    return device_map.get(device, device)


def _get_openvino_device(device: str = None) -> str:
    """
    获取 OpenVINO 设备字符串。
    注意：Ultralytics 使用小写来区分 OpenVINO 设备和 PyTorch 设备
    
    Args:
        device: 设备名称，如 'CPU', 'GPU', 'AUTO' 等
        
    Returns:
        OpenVINO 格式的设备字符串（大写）
    """
    if not device:
        return "AUTO"
    
    device = device.upper()
    
    # 映射常用设备名称到 OpenVINO 格式
    device_map = {
        'AUTO': 'AUTO',
        'CPU': 'CPU',
        'GPU': 'GPU',
        'GPU.0': 'GPU.0',
        'GPU.1': 'GPU.1',
        'IGPU': 'GPU.0',  # 集成显卡
        'DGPU': 'GPU.1',  # 独立显卡
        'NPU': 'NPU',
    }
    
    return device_map.get(device, device)


def _format_device_for_backend(device: str, model_type: str) -> str:
    """
    根据后端类型格式化设备字符串。
    
    Args:
        device: 原始设备名称
        model_type: 模型类型 (pytorch, openvino, tensorrt)
        
    Returns:
        格式化后的设备字符串，None 表示不指定（使用默认值）
    """
    if not device:
        return None
    
    device_upper = device.upper()
    
    if model_type == "openvino":
        # OpenVINO 的设备参数格式: "cpu", "gpu", "npu" 等（小写）
        # Ultralytics 内部会转换为大写传递给 OpenVINO
        if device_upper == "CPU":
            return "cpu"
        elif device_upper in ["GPU", "GPU.0", "IGPU"]:
            return "gpu"
        elif device_upper in ["GPU.1", "DGPU"]:
            return "gpu.1"  # 某些版本的 OpenVINO 支持指定 GPU 索引
        elif device_upper == "NPU":
            return "npu"
        elif device_upper == "AUTO":
            return None  # 自动选择，不传递 device 参数
        else:
            return device.lower()
    elif model_type == "tensorrt":
        # TensorRT 使用 CUDA 设备索引，如 '0', '1' 或 'cpu'
        if device_upper == "CPU":
            return "cpu"
        elif device_upper.startswith("GPU"):
            # GPU.0 -> 0, GPU.1 -> 1
            return device_upper.split(".")[-1] if "." in device_upper else "0"
        else:
            return "0"  # 默认 GPU 0
    else:
        # PyTorch: cuda:0, cpu, 等
        if device_upper == "CPU":
            return "cpu"
        elif device_upper.startswith("GPU"):
            idx = device_upper.split(".")[-1] if "." in device_upper else "0"
            return f"cuda:{idx}"
        else:
            return device.lower()


def compute_sliding_positions(
    image_size: int,
    crop_size: int,
    overlap: float
) -> List[int]:
    """
    计算滑窗在某个维度上的所有起始位置。
    与 sliding_window.py 中的逻辑一致，但独立实现以避免循环依赖。

    Args:
        image_size: 图像在该维度上的尺寸
        crop_size: 滑窗尺寸
        overlap: 重叠率

    Returns:
        起始位置列表
    """
    if image_size <= crop_size:
        return [0]

    stride = int(crop_size * (1.0 - overlap))
    stride = max(stride, 1)

    positions = []
    pos = 0
    while pos + crop_size <= image_size:
        positions.append(pos)
        pos += stride

    if positions[-1] + crop_size < image_size:
        positions.append(image_size - crop_size)

    return positions


def infer_single_image(
    model,
    image: np.ndarray,
    crop_size: int = 640,
    overlap: float = 0.2,
    conf_thresh: float = 0.15,
    iou_thresh: float = 0.5,
    padding: int = 32,
    resize_size: int = None,
    device: str = None,
    use_morphology: bool = False,
    dilate_kernel: int = 3,
    erode_kernel: int = 3,
) -> Dict:
    """
    对单张大图进行滑窗推断，返回合并后的检测结果。

    Args:
        model: 加载好的 YOLO 模型
        image: 输入图像 (H, W) 或 (H, W, C)
        crop_size: 滑窗尺寸（默认 640）
        overlap: 滑窗重叠率（默认 0.2）
        conf_thresh: 置信度阈值（默认 0.15）
        iou_thresh: NMS IoU 阈值（默认 0.5）
        padding: 边缘填充像素数（默认 32）
        resize_size: 预处理缩放尺寸（None=不缩放，使用bicubic插值）

    Returns:
        结果字典：
        {
            "boxes": np.ndarray,       # (N, 4) xyxy 格式的检测框
            "scores": np.ndarray,      # (N,) 置信度
            "classes": np.ndarray,     # (N,) 类别ID
            "masks": list,             # N 个二值 Mask (原图尺寸)
            "overlay": np.ndarray,     # 可视化叠加图
            "mask_image": np.ndarray,  # 分割 Mask 彩色图
            "num_detections": int,     # 检测数量
        }
    """
    start_time = time.time()  # 开始计时
    
    orig_h, orig_w = image.shape[:2]

    # ---- 保存原图用于可视化（避免三通道形态学色差）----
    if len(image.shape) == 2:
        display_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 1:
        display_image = cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR)
    else:
        display_image = image.copy()

    # ---- 灰度图转三通道（用于模型推断）----
    if use_morphology:
        # 形态学三通道：B=原图, G=膨胀, R=腐蚀（与训练时一致）
        from core.preprocess import create_morphology_triple_channel
        image_3ch = create_morphology_triple_channel(image, dilate_kernel, erode_kernel)
    elif len(image.shape) == 2:
        image_3ch = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 1:
        image_3ch = cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR)
    else:
        image_3ch = image.copy()
    
    # ---- 预处理缩放（等比缩放，长边对齐）----
    if resize_size is not None and resize_size > 0:
        long_side = max(orig_h, orig_w)
        if long_side != resize_size:
            scale = resize_size / long_side
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            image_3ch = cv2.resize(image_3ch, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            display_image = cv2.resize(display_image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            orig_h, orig_w = new_h, new_w

    # ---- 边缘 Padding ----
    if padding > 0:
        padded = cv2.copyMakeBorder(
            image_3ch, padding, padding, padding, padding,
            cv2.BORDER_REFLECT_101
        )
    else:
        padded = image_3ch

    pad_h, pad_w = padded.shape[:2]

    # 获取模型类型
    model_type = getattr(model, '_model_type', 'pytorch')
    
    # 准备 predict 参数
    predict_kwargs = {
        'imgsz': crop_size,
        'conf': conf_thresh,
        'iou': iou_thresh,
        'verbose': False,
    }
    
    # 根据后端类型处理设备参数
    if model_type == 'openvino':
        # OpenVINO 模型：不传递 device 参数给 predict()
        # 因为 predict 的 device 参数会被错误地传递给 PyTorch 的 select_device
        # OpenVINO 的设备选择应该由模型加载时自动处理
        pass
    elif device:
        # PyTorch/TensorRT 模型：正常传递 device 参数
        formatted_device = _format_device_for_backend(device, model_type)
        if formatted_device:
            predict_kwargs['device'] = formatted_device
    
    # ---- 判断是否需要滑窗 ----
    if pad_h <= crop_size and pad_w <= crop_size:
        # 图像小于等于 crop_size，直接推断，不滑窗
        # 需要 Resize 到 crop_size
        resized = cv2.resize(padded, (crop_size, crop_size), interpolation=cv2.INTER_CUBIC)
        results = model.predict(resized, **predict_kwargs)
        # 将结果映射回 padded 尺寸
        all_boxes, all_scores, all_classes, all_masks = \
            _extract_results(results[0], crop_size, crop_size,
                           0, 0, pad_h, pad_w,
                           scale_x=pad_w / crop_size,
                           scale_y=pad_h / crop_size)
    else:
        # 滑窗推断
        y_positions = compute_sliding_positions(pad_h, crop_size, overlap)
        x_positions = compute_sliding_positions(pad_w, crop_size, overlap)

        all_boxes = []
        all_scores = []
        all_classes = []
        all_masks = []

        for y_start in y_positions:
            for x_start in x_positions:
                # 裁剪子图
                crop = padded[y_start:y_start + crop_size, x_start:x_start + crop_size]

                # 确保尺寸正确
                if crop.shape[0] != crop_size or crop.shape[1] != crop_size:
                    temp = np.zeros((crop_size, crop_size, 3), dtype=np.uint8)
                    temp[:crop.shape[0], :crop.shape[1]] = crop
                    crop = temp

                # 推断
                results = model.predict(crop, **predict_kwargs)

                # 提取结果并映射到 padded 坐标系
                boxes, scores, classes, masks = \
                    _extract_results(results[0], crop_size, crop_size,
                                   x_start, y_start, pad_h, pad_w)
                all_boxes.extend(boxes)
                all_scores.extend(scores)
                all_classes.extend(classes)
                all_masks.extend(masks)

    # ---- 合并结果并执行 NMS ----
    if len(all_boxes) > 0:
        boxes_arr = np.array(all_boxes)
        scores_arr = np.array(all_scores)
        classes_arr = np.array(all_classes)

        # 按类别执行 NMS
        keep_indices = _class_aware_nms(boxes_arr, scores_arr, classes_arr, iou_thresh)

        final_boxes = boxes_arr[keep_indices]
        final_scores = scores_arr[keep_indices]
        final_classes = classes_arr[keep_indices]
        final_masks = [all_masks[i] for i in keep_indices]
    else:
        final_boxes = np.empty((0, 4))
        final_scores = np.empty(0)
        final_classes = np.empty(0, dtype=int)
        final_masks = []

    # ---- 去除 Padding 偏移 ----
    if padding > 0 and len(final_boxes) > 0:
        final_boxes[:, 0] -= padding  # x1
        final_boxes[:, 1] -= padding  # y1
        final_boxes[:, 2] -= padding  # x2
        final_boxes[:, 3] -= padding  # y2
        # 裁剪到原图范围
        final_boxes[:, 0] = np.clip(final_boxes[:, 0], 0, orig_w)
        final_boxes[:, 1] = np.clip(final_boxes[:, 1], 0, orig_h)
        final_boxes[:, 2] = np.clip(final_boxes[:, 2], 0, orig_w)
        final_boxes[:, 3] = np.clip(final_boxes[:, 3], 0, orig_h)

        # Mask 也需要去除 Padding
        trimmed_masks = []
        for m in final_masks:
            if m is not None and m.shape[0] >= padding and m.shape[1] >= padding:
                trimmed = m[padding:padding + orig_h, padding:padding + orig_w]
                trimmed_masks.append(trimmed)
            else:
                trimmed_masks.append(np.zeros((orig_h, orig_w), dtype=np.uint8))
        final_masks = trimmed_masks

    # ---- 生成可视化图像（使用原图而非形态学三通道图，避免色差）----
    overlay = _draw_overlay(display_image, final_boxes, final_scores, final_classes, final_masks)
    # 同时生成形态学三通道叠加图（供用户切换查看）
    overlay_morph = _draw_overlay(image_3ch, final_boxes, final_scores, final_classes, final_masks) if use_morphology else None
    mask_image = _draw_mask_image(orig_h, orig_w, final_classes, final_masks)
    
    # ---- 计算检测时间 ----
    elapsed_time = time.time() - start_time

    return {
        "boxes": final_boxes,
        "scores": final_scores,
        "classes": final_classes,
        "masks": final_masks,
        "overlay": overlay,
        "overlay_morph": overlay_morph,
        "mask_image": mask_image,
        "num_detections": len(final_boxes),
        "inference_time": elapsed_time,  # 检测时间（秒）
    }


def _extract_results(
    result, crop_w, crop_h, offset_x, offset_y, pad_h, pad_w,
    scale_x=1.0, scale_y=1.0
):
    """
    从单个子图的推断结果中提取 Box、Score、Class、Mask，
    并将坐标映射到 padded 图像的坐标系。

    Args:
        result: Ultralytics 推断结果对象
        crop_w, crop_h: 子图尺寸（如 640x640）
        offset_x, offset_y: 子图在 padded 图中的偏移
        pad_h, pad_w: padded 图像尺寸
        scale_x, scale_y: 缩放因子（当图像被 Resize 时使用）

    Returns:
        (boxes, scores, classes, masks) 四个列表
    """
    boxes = []
    scores = []
    classes = []
    masks = []

    if result.boxes is None or len(result.boxes) == 0:
        return boxes, scores, classes, masks

    # 提取 Box (xyxy 格式)
    box_data = result.boxes.xyxy.cpu().numpy()
    conf_data = result.boxes.conf.cpu().numpy()
    cls_data = result.boxes.cls.cpu().numpy().astype(int)

    # 提取 Mask 原型 (N, mask_h, mask_w)，通常是 (N, 160, 160)
    mask_data = None
    if result.masks is not None:
        mask_data = result.masks.data.cpu().numpy()

    for i in range(len(box_data)):
        # 获取模型输出坐标（在 crop_w x crop_h 尺度下，如 640x640）
        px1, py1, px2, py2 = box_data[i]
        
        # 映射 Box 坐标到 padded 坐标系
        x1 = px1 * scale_x + offset_x
        y1 = py1 * scale_y + offset_y
        x2 = px2 * scale_x + offset_x
        y2 = py2 * scale_y + offset_y

        boxes.append([x1, y1, x2, y2])
        scores.append(float(conf_data[i]))
        classes.append(int(cls_data[i]))

        # 处理 Mask - 参考 OpenVINO 实现：在原型尺度下裁剪 ROI 再上采样
        if mask_data is not None and i < len(mask_data):
            m = mask_data[i]  # (mask_h, mask_w)，如 (160, 160)
            mask_h, mask_w = m.shape
            
            # 计算缩放比例：模型输入尺寸 / mask原型尺寸 = 640/160 = 4
            ratio = crop_w / mask_w  # 假设 w=h=640, mask_w=160，则 ratio=4
            
            # 在 mask 原型尺度下计算 ROI（参考 C++ 代码）
            mask_x1 = max(0, int(px1 / ratio))
            mask_y1 = max(0, int(py1 / ratio))
            mask_x2 = min(mask_w - 1, int(px2 / ratio))
            mask_y2 = min(mask_h - 1, int(py2 / ratio))
            
            if mask_x2 > mask_x1 and mask_y2 > mask_y1:
                # 在 160x160 尺度下裁剪 ROI
                mask_roi = m[mask_y1:mask_y2, mask_x1:mask_x2]
                
                # 计算目标尺寸（在 crop 尺度下的像素数）
                target_w = int((px2 - px1) * scale_x)
                target_h = int((py2 - py1) * scale_y)
                target_w = max(1, target_w)
                target_h = max(1, target_h)
                
                # 将 ROI 上采样到检测框尺寸
                mask_resized = cv2.resize(mask_roi, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                m_binary = (mask_resized > 0.5).astype(np.uint8)
                
                # 放置到 full mask 的对应位置（考虑 offset 和缩放）
                full_mask = np.zeros((pad_h, pad_w), dtype=np.uint8)
                
                # 计算放置位置（考虑 scale 和 offset）
                dst_x1 = int(px1 * scale_x + offset_x)
                dst_y1 = int(py1 * scale_y + offset_y)
                dst_x2 = dst_x1 + target_w
                dst_y2 = dst_y1 + target_h
                
                # 裁剪到有效范围
                dst_x1 = max(0, min(dst_x1, pad_w))
                dst_y1 = max(0, min(dst_y1, pad_h))
                dst_x2 = max(0, min(dst_x2, pad_w))
                dst_y2 = max(0, min(dst_y2, pad_h))
                
                actual_w = dst_x2 - dst_x1
                actual_h = dst_y2 - dst_y1
                
                if actual_h > 0 and actual_w > 0:
                    full_mask[dst_y1:dst_y2, dst_x1:dst_x2] = m_binary[:actual_h, :actual_w]
                
                masks.append(full_mask)
            else:
                masks.append(np.zeros((pad_h, pad_w), dtype=np.uint8))
        else:
            masks.append(np.zeros((pad_h, pad_w), dtype=np.uint8))

    return boxes, scores, classes, masks


def _class_aware_nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    classes: np.ndarray,
    iou_thresh: float
) -> List[int]:
    """
    按类别执行 NMS（Non-Maximum Suppression）。
    不同类别之间不会互相抑制。

    Args:
        boxes: (N, 4) xyxy 格式
        scores: (N,) 置信度
        classes: (N,) 类别ID
        iou_thresh: IoU 阈值

    Returns:
        保留的索引列表
    """
    if len(boxes) == 0:
        return []

    keep = []
    unique_classes = np.unique(classes)

    for cls in unique_classes:
        cls_mask = classes == cls
        cls_indices = np.where(cls_mask)[0]
        cls_boxes = boxes[cls_mask]
        cls_scores = scores[cls_mask]

        # 使用 OpenCV 的 NMS
        indices = cv2.dnn.NMSBoxes(
            bboxes=cls_boxes.tolist(),
            scores=cls_scores.tolist(),
            score_threshold=0.0,  # 已经过滤过了
            nms_threshold=iou_thresh
        )

        if len(indices) > 0:
            indices = indices.flatten()
            keep.extend(cls_indices[indices].tolist())

    return sorted(keep)


def _draw_overlay(
    image: np.ndarray,
    boxes: np.ndarray,
    scores: np.ndarray,
    classes: np.ndarray,
    masks: list
) -> np.ndarray:
    """
    在原图上绘制检测框和半透明 Mask 叠加。

    Args:
        image: 原图 (H, W, 3)
        boxes: (N, 4) xyxy
        scores: (N,)
        classes: (N,)
        masks: N 个二值 Mask

    Returns:
        叠加后的图像
    """
    overlay = image.copy()
    h, w = overlay.shape[:2]

    for i in range(len(boxes)):
        cls_id = int(classes[i])
        color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
        score = float(scores[i])

        # 绘制半透明 Mask
        if i < len(masks) and masks[i] is not None:
            m = masks[i]
            # 确保 Mask 尺寸与图像一致
            if m.shape[:2] != (h, w):
                m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
            mask_region = m > 0
            mask_color = np.zeros_like(overlay)
            mask_color[mask_region] = color
            overlay = cv2.addWeighted(overlay, 1.0, mask_color, 0.4, 0)

        # 绘制检测框
        x1, y1, x2, y2 = boxes[i].astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)

        # 绘制标签
        label = f"C{cls_id} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(overlay, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(overlay, label, (x1 + 2, y1 - 4),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return overlay


def _draw_mask_image(
    height: int,
    width: int,
    classes: np.ndarray,
    masks: list
) -> np.ndarray:
    """
    生成纯分割 Mask 彩色图（黑色背景 + 彩色缺陷区域）。

    Args:
        height, width: 图像尺寸
        classes: (N,) 类别ID
        masks: N 个二值 Mask

    Returns:
        彩色 Mask 图像 (H, W, 3)
    """
    mask_image = np.zeros((height, width, 3), dtype=np.uint8)

    for i in range(len(masks)):
        if masks[i] is None:
            continue
        cls_id = int(classes[i])
        color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
        m = masks[i]
        if m.shape[:2] != (height, width):
            m = cv2.resize(m, (width, height), interpolation=cv2.INTER_NEAREST)
        mask_image[m > 0] = color

    return mask_image
