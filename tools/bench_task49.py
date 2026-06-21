# -*- coding: utf-8 -*-
"""task 49 完整速度对比：crop=1280 + resize=2560 + overlap=0.25"""
import sys, time
import numpy as np
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')
from core.inference import infer_single_image, compute_sliding_positions
from ultralytics import YOLO
import cv2

PT   = r'D:\yolo26s_platform\storage\runs\task_49\runs\train\weights\best.pt'
OV   = r'D:\yolo26s_platform\storage\runs\task_49\runs\train\weights\best_openvino_model'
ONNX = r'D:\yolo26s_platform\storage\runs\task_49\runs\train\weights\best.onnx'

SRC = r'D:\yolo26s_platform\storage\uploads\35\009cdf26_6717383.bmp'
buf = np.fromfile(SRC, dtype=np.uint8)
big = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
if big.ndim == 2:
    big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
img2560 = cv2.resize(big, (2560, 2560), interpolation=cv2.INTER_CUBIC)

print(f'输入图: 2560x2560  crop=1280  overlap=0.25')
print(f'滑窗位置（含 padding=32 后 2624）: {compute_sliding_positions(2624, 1280, 0.25)}')
positions = compute_sliding_positions(2624, 1280, 0.25)
print(f'滑窗总数: {len(positions)}x{len(positions)} = {len(positions)**2} crops')
print()

configs = [
    ('PT-CUDA',     PT,   'cuda:0',     'pytorch'),
    ('PT-CPU',      PT,   'cpu',        'pytorch'),
    ('OV-CPU',      OV,   'CPU',        'openvino'),
    ('OV-GPU.0',    OV,   'GPU.0',      'openvino'),
    ('ONNX-CPU',    ONNX, 'cpu',        'onnx'),
]

print(f'{"config":<12} {"best_ms":<10} {"median_ms":<10} {"per_crop":<10} {"n_det":<6}')
print('-' * 55)
for label, path, dev, kind in configs:
    try:
        if kind == 'pytorch':
            m = YOLO(path)
            if 'cuda' in dev:
                m.to(dev)
            m._model_type = 'pytorch'
        else:
            m = YOLO(path, task='segment')
            m._model_type = kind
        # 预热
        _ = infer_single_image(m, img2560, crop_size=1280, overlap=0.25,
                                conf_thresh=0.05, iou_thresh=0.5,
                                use_morphology=True, dilate_kernel=15, erode_kernel=15,
                                device=dev)
        ts = []
        for _ in range(3):
            t0 = time.time()
            r = infer_single_image(m, img2560, crop_size=1280, overlap=0.25,
                                    conf_thresh=0.05, iou_thresh=0.5,
                                    use_morphology=True, dilate_kernel=15, erode_kernel=15,
                                    device=dev)
            ts.append(time.time() - t0)
        best = min(ts) * 1000
        med = sorted(ts)[1] * 1000
        per_crop = best / (len(positions) ** 2)
        print(f'{label:<12} {best:>7.0f}ms  {med:>7.0f}ms  {per_crop:>6.1f}ms   n={r["num_detections"]}')
    except Exception as e:
        print(f'{label:<12} FAIL: {str(e)[:50]}')
