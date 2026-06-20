# -*- coding: utf-8 -*-
"""task 48 全面速度对比：PT/OV/ONNX × CPU/GPU.0 × 多尺寸"""
import sys, time
import numpy as np
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')
from core.inference import infer_single_image
from ultralytics import YOLO
import cv2

PT   = r'D:\yolo26s_platform\storage\runs\task_48\runs\train\weights\best.pt'
OV   = r'D:\yolo26s_platform\storage\runs\task_48\runs\train\weights\best_openvino_model'
ONNX = r'D:\yolo26s_platform\storage\runs\task_48\runs\train\weights\best.onnx'

# 测试图：4096 原图、1820、640
SRC = r'D:\yolo26s_platform\storage\uploads\35\009cdf26_6717383.bmp'
buf = np.fromfile(SRC, dtype=np.uint8)
big = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
if big.ndim == 2:
    big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)

# 因测试图本身是 1971x1845，4096 用 resize 模拟，640 用 resize
def get_img(size):
    if size == big.shape[0]:
        return big
    return cv2.resize(big, (size, size), interpolation=cv2.INTER_CUBIC)

# resize 到目标尺寸（模拟生产输入）
sizes = [(640, '640'), (1820, '1820'), (4096, '4096')]

def bench(model, label, dev, img, n=3):
    # 预热
    _ = infer_single_image(model, img, crop_size=640, overlap=0.4,
                            conf_thresh=0.05, iou_thresh=0.5,
                            use_morphology=True, dilate_kernel=15, erode_kernel=15,
                            device=dev)
    ts = []
    for _ in range(n):
        t0 = time.time()
        r = infer_single_image(model, img, crop_size=640, overlap=0.4,
                                conf_thresh=0.05, iou_thresh=0.5,
                                use_morphology=True, dilate_kernel=15, erode_kernel=15,
                                device=dev)
        ts.append(time.time() - t0)
    return min(ts) * 1000, r['num_detections']


configs = [
    ('PT-CUDA',     PT,   'cuda:0',     'pytorch'),
    ('PT-CPU',      PT,   'cpu',        'pytorch'),
    ('OV-CPU',      OV,   'CPU',        'openvino'),
    ('OV-GPU.0',    OV,   'GPU.0',      'openvino'),
    ('ONNX-CPU',    ONNX, 'cpu',        'onnx'),
]

print(f'{"config":<15}', *[f'{lbl:>14}' for _, lbl in sizes])
print('-' * 70)
for cfg_label, path, dev, kind in configs:
    if kind == 'pytorch':
        m = YOLO(path)
        if 'cuda' in dev:
            m.to(dev)
        m._model_type = 'pytorch'
    else:
        m = YOLO(path, task='segment')
        m._model_type = kind
    row = [cfg_label]
    for sz, lbl in sizes:
        try:
            img = get_img(sz)
            ms, n = bench(m, cfg_label, dev, img)
            row.append(f'{ms:>7.0f}ms n={n:<3}')
        except Exception as e:
            row.append(f'{"FAIL":>14}')
    print(f'{row[0]:<15}', *[f'{c:>14}' for c in row[1:]])
