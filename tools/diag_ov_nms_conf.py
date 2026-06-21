# -*- coding: utf-8 -*-
"""验证 nms=true 时把 conf 阈值固化到低值能否解决低 conf 漏检"""
import sys, shutil, time
from pathlib import Path
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')

import numpy as np
import cv2
from ultralytics import YOLO
from core.inference import infer_single_image

IMG = Path(r"D:\yolo26s_platform\storage\runs\inference\6512a665314b_original.png")
PT  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best.pt")

# 导出 nms=true + conf=0.001 的版本
OUT_DIR = Path(r"D:\yolo26s_platform\tools\_diag_low_conf_nms")
if OUT_DIR.exists(): shutil.rmtree(OUT_DIR)
OUT_DIR.mkdir(parents=True)
work = OUT_DIR / "best.pt"
shutil.copy2(PT, work)

print("[setup] 导出 nms=true + conf=0.001 的 OV ...")
m = YOLO(str(work))
out = m.export(format="openvino", imgsz=640, half=False, nms=True, conf=0.001)
print(f"[setup] OK -> {out}")
TARGET = Path(out)

KW = dict(crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.30,
          resize_size=2560,
          use_morphology=True, dilate_kernel=3, erode_kernel=3)

img = cv2.imread(str(IMG))
print(f"\n图: {IMG.name}  shape={img.shape}")
print(f"参数: {KW}\n")

print(f"--- OV nms=true + 导出 conf=0.001 (运行时 conf=0.15) ---")
mm = YOLO(str(TARGET), task='segment')
r = infer_single_image(mm, img.copy(), device="CPU", **KW)
print(f"  检出: {r['num_detections']}")
for i in range(r['num_detections']):
    box = r['boxes'][i]
    cls = int(r['classes'][i])
    score = float(r['scores'][i])
    print(f"    cls={cls} conf={score:.3f} box=({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f})")
