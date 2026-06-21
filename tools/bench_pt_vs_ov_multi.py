# -*- coding: utf-8 -*-
"""跨多张图统计 PT-CUDA vs OV-CPU vs OV-GPU.0 的检出差异
确认 CUDA vs CPU 的浮点差异在实际数据集上的影响规模"""
import sys, time, random
from pathlib import Path
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')

import numpy as np
import cv2
from ultralytics import YOLO
from core.inference import infer_single_image

UPLOADS = Path(r"D:\yolo26s_platform\storage\uploads\8")
PT  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best.pt")
OV  = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best_openvino_model")

# 抽 20 张
random.seed(42)
imgs = sorted(UPLOADS.glob("*.bmp"))
N = 20
if len(imgs) > N:
    imgs = random.sample(imgs, N)
print(f"测试图数：{len(imgs)} 张\n")

KW = dict(crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.30,
          resize_size=2560,
          use_morphology=True, dilate_kernel=3, erode_kernel=3)

# 一次加载三个 backend
m_pt = YOLO(str(PT), task='segment')
m_ov = YOLO(str(OV), task='segment')

def predict(m, img, dev):
    return infer_single_image(m, img.copy(), device=dev, **KW)

def iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    ua = (a[2]-a[0]) * (a[3]-a[1]); ub = (b[2]-b[0]) * (b[3]-b[1])
    return inter / max(1e-6, ua + ub - inter)

def to_set(r):
    out = []
    for i in range(r['num_detections']):
        b = r['boxes'][i]; c = int(r['classes'][i]); s = float(r['scores'][i])
        out.append((c, s, b[0], b[1], b[2], b[3]))
    return out

def match(A, B, thr=0.5):
    """返回 (匹配数, 仅A, 仅B)"""
    used = set(); matched = 0
    for a in A:
        best = 0; best_j = -1
        for j, b in enumerate(B):
            if j in used: continue
            if a[0] != b[0]: continue  # 同类
            v = iou(a[2:], b[2:])
            if v > best: best, best_j = v, j
        if best >= thr:
            matched += 1; used.add(best_j)
    return matched, len(A) - matched, len(B) - matched

print(f"{'图':<40} {'CUDA':>5} {'OV-CPU':>7} {'OV-iGPU':>8} {'OV-dGPU':>8} {'差异'}")
print("-" * 95)

stats = {'cuda': 0, 'ovcpu': 0, 'ovigpu': 0, 'ovdgpu': 0,
         'cuda_extra_vs_ovcpu': 0, 'ovcpu_extra_vs_cuda': 0,
         'identical_images': 0, 'differ_images': 0}
results_log = []

for p in imgs:
    img = cv2.imread(str(p))
    if img is None: continue
    rc  = to_set(predict(m_pt,  img, "0"))
    rcc = to_set(predict(m_pt,  img, "cpu"))
    roc = to_set(predict(m_ov, img, "CPU"))
    rg0 = to_set(predict(m_ov, img, "GPU.0"))
    rg1 = to_set(predict(m_ov, img, "GPU.1"))

    n_cuda, n_pt_cpu, n_ovcpu, n_ig, n_dg = len(rc), len(rcc), len(roc), len(rg0), len(rg1)

    # 主对比：PT-CUDA vs OV-CPU（最接近部署场景）
    m_, only_cuda, only_ov = match(rc, roc)
    differ = (only_cuda + only_ov) > 0

    stats['cuda']    += n_cuda
    stats['ovcpu']   += n_ovcpu
    stats['ovigpu']  += n_ig
    stats['ovdgpu']  += n_dg
    stats['cuda_extra_vs_ovcpu'] += only_cuda
    stats['ovcpu_extra_vs_cuda'] += only_ov
    if differ: stats['differ_images'] += 1
    else: stats['identical_images'] += 1

    diff_tag = f"CUDA独{only_cuda} OV独{only_ov}" if differ else "一致"
    print(f"{p.name[:38]:<40} {n_cuda:>5} {n_ovcpu:>7} {n_ig:>8} {n_dg:>8}  {diff_tag}")
    results_log.append((p.name, rc, rcc, roc, rg0, rg1))

print()
print("=" * 60)
print("汇总")
print("=" * 60)
print(f"图数: {len(imgs)}")
print(f"  - CUDA / OV-CPU 完全一致: {stats['identical_images']}")
print(f"  - 有差异:                {stats['differ_images']}")
print()
print(f"总检出数:  CUDA={stats['cuda']}  OV-CPU={stats['ovcpu']}  OV-iGPU={stats['ovigpu']}  OV-dGPU={stats['ovdgpu']}")
print(f"CUDA 独有 (OV 漏): {stats['cuda_extra_vs_ovcpu']}")
print(f"OV 独有 (CUDA 漏): {stats['ovcpu_extra_vs_cuda']}")

# 同后端 OV 三 device 一致性快速检查
ov_consistent = sum(1 for _, _, _, c, g0, g1 in results_log if len(c) == len(g0) == len(g1))
print(f"\nOV 内部一致 (CPU=iGPU=dGPU 检出数相同): {ov_consistent}/{len(imgs)}")
