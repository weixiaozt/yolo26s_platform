# -*- coding: utf-8 -*-
"""
标注导入服务：Mask PNG + XML → 平台内部 YOLO polygon 格式
"""

import cv2
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List


def scan_xml_classes(xml_dir: str) -> Dict[str, int]:
    """扫描所有 XML 文件，收集全部类别名 → {类别名: 出现次数}"""
    class_counts: Dict[str, int] = {}
    for xml_path in sorted(Path(xml_dir).glob("*.xml")):
        try:
            tree = ET.parse(str(xml_path))
            for obj in tree.getroot().findall("object"):
                name_elem = obj.find("name")
                if name_elem is None:
                    name_elem = obj.find("n")
                if name_elem is not None and name_elem.text:
                    cls = name_elem.text.strip()
                    class_counts[cls] = class_counts.get(cls, 0) + 1
        except Exception:
            continue
    return class_counts


def mask_to_polygons(
    mask_path: str,
    class_mapping: Dict[int, int],
    min_area: int = 20,
) -> List[Dict]:
    """
    将 Mask PNG 转为 polygon 标注列表。
    Args:
        mask_path: Mask PNG 路径
        class_mapping: {mask像素值: 平台class_index}
        min_area: 最小轮廓面积（过滤噪点）
    Returns:
        [{"class_index": 0, "points": [[x,y],...], "area": 123}, ...]
    """
    mask = cv2.imread(mask_path, cv2.IMREAD_UNCHANGED)
    if mask is None:
        return []
    if len(mask.shape) == 3:
        mask = mask[:, :, 0]

    h, w = mask.shape[:2]
    annotations = []
    for pixel_val, class_index in class_mapping.items():
        if pixel_val == 0:
            continue
        binary = (mask == pixel_val).astype(np.uint8) * 255
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or len(contour) < 3:
                continue
            # 归一化到 0~1（除以 Mask 宽高）
            points = [[round(pt[0] / w, 6), round(pt[1] / h, 6)] for pt in contour.reshape(-1, 2)]
            annotations.append({"class_index": class_index, "points": points, "area": area})
    return annotations


def parse_voc_xml(xml_path: str) -> Dict:
    """
    解析单个 Pascal VOC XML 文件 → 图像信息和 bbox 列表。
    Returns:
        {
            "filename": str,
            "width": int,
            "height": int,
            "objects": [{"name": str, "xmin", "ymin", "xmax", "ymax"}, ...]
        }
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    size = root.find("size")
    w = int(size.findtext("width", "0")) if size is not None else 0
    h = int(size.findtext("height", "0")) if size is not None else 0
    filename = root.findtext("filename", Path(xml_path).stem)

    objects = []
    for obj in root.findall("object"):
        name_elem = obj.find("name")
        if name_elem is None:
            name_elem = obj.find("n")
        if name_elem is None or not name_elem.text:
            continue
        cls_name = name_elem.text.strip()

        bndbox = obj.find("bndbox")
        if bndbox is None:
            continue
        try:
            xmin = float(bndbox.findtext("xmin", "0"))
            ymin = float(bndbox.findtext("ymin", "0"))
            xmax = float(bndbox.findtext("xmax", "0"))
            ymax = float(bndbox.findtext("ymax", "0"))
        except (ValueError, TypeError):
            continue
        if xmax <= xmin or ymax <= ymin:
            continue

        objects.append({
            "name": cls_name,
            "xmin": xmin, "ymin": ymin,
            "xmax": xmax, "ymax": ymax,
        })

    return {"filename": filename, "width": w, "height": h, "objects": objects}


def bbox_to_polygon4(xmin: float, ymin: float, xmax: float, ymax: float,
                     img_w: int, img_h: int) -> List[Dict]:
    """
    将 bbox 转换为 4 点多边形（归一化 0~1），与平台 polygon 格式兼容。
    顺序：左上 → 右上 → 右下 → 左下
    """
    if img_w <= 0 or img_h <= 0:
        return []
    return [
        {"x": round(xmin / img_w, 6), "y": round(ymin / img_h, 6)},
        {"x": round(xmax / img_w, 6), "y": round(ymin / img_h, 6)},
        {"x": round(xmax / img_w, 6), "y": round(ymax / img_h, 6)},
        {"x": round(xmin / img_w, 6), "y": round(ymax / img_h, 6)},
    ]


def auto_detect_pixel_class_mapping(
    xml_dir: str,
    mask_dir: str,
) -> Dict[int, str]:
    """
    通过 XML bbox + Mask 像素对照，自动建立 像素值→类别名 映射。
    原理：对每个 XML 中的 bbox，看 Mask 对应区域里最常见的非零像素值。
    """
    pixel_to_class: Dict[int, str] = {}

    for xml_path in sorted(Path(xml_dir).glob("*.xml")):
        stem = xml_path.stem
        mask_path = None
        for ext in ['.png', '.bmp', '.tif', '.tiff']:
            candidate = Path(mask_dir) / f"{stem}{ext}"
            if candidate.exists():
                mask_path = candidate
                break
        if not mask_path:
            continue

        mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mask is None:
            continue
        if len(mask.shape) == 3:
            mask = mask[:, :, 0]
        mask_h, mask_w = mask.shape

        # 解析 XML
        try:
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
            xml_w = int(root.findtext(".//size/width", "0"))
            xml_h = int(root.findtext(".//size/height", "0"))
        except:
            xml_w, xml_h = 0, 0

        for obj in root.findall("object"):
            name_elem = obj.find("name")
            if name_elem is None:
                name_elem = obj.find("n")
            if name_elem is None or not name_elem.text:
                continue
            cls_name = name_elem.text.strip()
            bbox_elem = obj.find("bndbox")
            if bbox_elem is None:
                continue

            xmin = int(float(bbox_elem.findtext("xmin", "0")))
            ymin = int(float(bbox_elem.findtext("ymin", "0")))
            xmax = int(float(bbox_elem.findtext("xmax", "0")))
            ymax = int(float(bbox_elem.findtext("ymax", "0")))

            # 坐标缩放（XML 记录的是原图尺寸，Mask 可能被 resize 过）
            if xml_w > 0 and xml_h > 0 and (xml_w != mask_w or xml_h != mask_h):
                sx, sy = mask_w / xml_w, mask_h / xml_h
                xmin, ymin = int(xmin * sx), int(ymin * sy)
                xmax, ymax = int(xmax * sx), int(ymax * sy)

            xmin = max(0, min(xmin, mask_w - 1))
            xmax = max(0, min(xmax, mask_w - 1))
            ymin = max(0, min(ymin, mask_h - 1))
            ymax = max(0, min(ymax, mask_h - 1))
            if xmax <= xmin or ymax <= ymin:
                continue

            roi = mask[ymin:ymax, xmin:xmax]
            nonzero = roi[roi > 0]
            if len(nonzero) == 0:
                continue

            vals, counts = np.unique(nonzero, return_counts=True)
            dominant_val = int(vals[np.argmax(counts)])
            if dominant_val not in pixel_to_class:
                pixel_to_class[dominant_val] = cls_name

    return pixel_to_class
