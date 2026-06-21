# -*- coding: utf-8 -*-
"""复现 InferenceView 上 OV 漏检 bug：用户那张图，PT vs OV(nms=true) vs OV(nms=false) 滑窗对比"""
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
OV_NMS_TRUE  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best_openvino_model")
OV_NMS_FALSE = Path(r"D:\yolo26s_platform\tools\_diag_no_nms_openvino_model")

# 准备一份 nms=false 的 OV（如果不存在）
if not OV_NMS_FALSE.exists():
    print("[setup] 导出 nms=false 的 OV 用于对比 ...")
    work = OV_NMS_FALSE.parent / "_diag_best.pt"
    shutil.copy2(PT, work)
    m = YOLO(str(work))
    out = m.export(format="openvino", imgsz=640, half=False)
    if Path(out).resolve() != OV_NMS_FALSE.resolve():
        # ultralytics 默认 best_openvino_model 同级；移动到目标
        shutil.move(out, OV_NMS_FALSE)
    work.unlink(missing_ok=True)
    print(f"[setup] OK -> {OV_NMS_FALSE}")

# 推理参数（跟 InferenceView 显示的一致）
KW = dict(crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.30,
          resize_size=2560,
          use_morphology=True, dilate_kernel=3, erode_kernel=3)

img = cv2.imread(str(IMG))
print(f"\n图: {IMG.name}  shape={img.shape}")
print(f"参数: {KW}\n")

for label, path, dev in [
    ("PT-CPU",          PT,            "cpu"),
    ("OV nms=true",     OV_NMS_TRUE,   "CPU"),
    ("OV nms=false",    OV_NMS_FALSE,  "CPU"),
]:
    print(f"--- {label} ({path.name}) ---")
    t0 = time.time()
    m = YOLO(str(path), task='segment')
    r = infer_single_image(m, img.copy(), device=dev, **KW)
    print(f"  耗时: {(time.time()-t0)*1000:.0f}ms  检出: {r['num_detections']}")
    if r['num_detections'] > 0:
        for i in range(r['num_detections']):
            box = r['boxes'][i]
            cls = int(r['classes'][i])
            score = float(r['scores'][i])
            print(f"    cls={cls} conf={score:.3f} box=({box[0]:.0f},{box[1]:.0f})-({box[2]:.0f},{box[3]:.0f})")
    print()
