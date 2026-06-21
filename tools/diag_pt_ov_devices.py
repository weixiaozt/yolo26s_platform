# -*- coding: utf-8 -*-
"""对比 PT vs OV(CPU/iGPU/dGPU) 在同一张图上的推理差异
现在 best_openvino_model 是 nms=false 的版本，理论上应该跟 PT 一致"""
import sys, shutil, time
from pathlib import Path
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')

import numpy as np
import cv2
from ultralytics import YOLO
from core.inference import infer_single_image

IMG = Path(r"D:\yolo26s_platform\storage\runs\inference\b86cc7a01db9_original.png")
PT  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best.pt")
OV  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best_openvino_model")

# 先确认 OV nms 状态
meta = (OV / "metadata.yaml").read_text(encoding='utf-8')
print("[metadata 关键字段]")
for line in meta.splitlines():
    if any(k in line for k in ('nms:', 'end2end:', 'conf')):
        print(f"  {line}")
print()

KW = dict(crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.30,
          resize_size=2560,
          use_morphology=True, dilate_kernel=3, erode_kernel=3)

img = cv2.imread(str(IMG))
print(f"图: {IMG.name}  shape={img.shape}\n")

def fmt_dets(r):
    out = []
    for i in range(r['num_detections']):
        box = r['boxes'][i]
        cls = int(r['classes'][i])
        score = float(r['scores'][i])
        out.append((cls, score, int(box[0]), int(box[1]), int(box[2]), int(box[3])))
    return sorted(out, key=lambda x: -x[1])  # 按 conf 降序

for label, path, dev in [
    ("PT-CUDA",     PT, "0"),
    ("PT-CPU",      PT, "cpu"),
    ("OV-CPU",      OV, "CPU"),
    ("OV-GPU.0",    OV, "GPU.0"),
    ("OV-GPU.1",    OV, "GPU.1"),
]:
    print(f"--- {label} ---")
    try:
        t0 = time.time()
        m = YOLO(str(path), task='segment')
        r = infer_single_image(m, img.copy(), device=dev, **KW)
        print(f"  耗时: {(time.time()-t0)*1000:.0f}ms  检出: {r['num_detections']}")
        for d in fmt_dets(r):
            print(f"    cls={d[0]} conf={d[1]:.3f} box=({d[2]},{d[3]})-({d[4]},{d[5]})")
    except Exception as e:
        print(f"  失败: {type(e).__name__}: {e}")
    print()
