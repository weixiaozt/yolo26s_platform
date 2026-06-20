# -*- coding: utf-8 -*-
"""快速对比 .pt 与 OpenVINO 在同一张图上的滑窗推理结果"""
import sys, time, numpy as np
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')
from core.inference import load_model, infer_single_image
import cv2

PATHS = [
    r'D:\yolo26s_platform\storage\uploads\35\009cdf26_6717383.bmp',
    r'D:\yolo26s_platform\storage\uploads\35\01d32107_划伤_7_56_9_443.bmp',
    r'D:\yolo26s_platform\storage\uploads\35\0e916905_脏污_7_56_9_443.bmp',
]
PT       = r'D:\yolo26s_platform\storage\runs\task_43\runs\train\weights\best.pt'
OV_E2E   = r'D:\yolo26s_platform\storage\runs\task_43\runs\train\weights\best_openvino_model\best.xml'
OV_NOE2E = r'D:\yolo26s_platform\storage\runs\_diag_e2e_false\best_openvino_model\best.xml'

mpt, _    = load_model(PT, device='cuda:0')
mov_old, _ = load_model(OV_E2E)
mov_new, _ = load_model(OV_NOE2E)

for p in PATHS:
    buf = np.fromfile(p, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    name = p.split('\\')[-1]
    print(f'=== img: {name} shape: {img.shape}')

    def run(m, dev, label):
        t0 = time.time()
        r = infer_single_image(m, img, crop_size=640, overlap=0.2,
                               conf_thresh=0.15, iou_thresh=0.5,
                               use_morphology=False, device=dev)
        scores = sorted(r["scores"].tolist(), reverse=True)[:6]
        print(f'  {label}: n={r["num_detections"]}  t={time.time()-t0:.2f}s  scores={scores}')

    run(mpt, 'cuda:0', 'PT_CUDA   ')
    run(mov_old, 'CPU', 'OV_e2e=ON ')
    run(mov_new, 'CPU', 'OV_e2e=OFF')
