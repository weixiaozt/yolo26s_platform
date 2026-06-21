# -*- coding: utf-8 -*-
"""task 52 综合测试：速度 + 一致性 + 崩边检出"""
import sys, time
import numpy as np
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')
from core.inference import infer_single_image
from ultralytics import YOLO
import cv2
import sqlalchemy as sa
from pathlib import Path

PT   = r'D:\yolo26s_platform\storage\runs\task_52\runs\train\weights\best.pt'
OV   = r'D:\yolo26s_platform\storage\runs\task_52\runs\train\weights\best_openvino_model'
ONNX = r'D:\yolo26s_platform\storage\runs\task_52\runs\train\weights\best.onnx'

CROP_SIZE = 640
OVERLAP = 0.2
RESIZE = 2560
MORPH_KERNEL = 3

# 取 project 8 中含崩边的图（task 52 训练数据集中）
e = sa.create_engine('mysql+pymysql://root:123456@localhost:3306/yolo_seg')
with e.connect() as c:
    rows = c.execute(sa.text('''
        SELECT DISTINCT i.id, i.filename, i.file_path FROM annotations a
        JOIN images i ON a.image_id=i.id
        JOIN defect_classes dc ON a.class_id=dc.id
        WHERE i.project_id=8 AND dc.class_index=1
        LIMIT 3
    ''')).fetchall()
TEST_IMGS = []
upload = Path(r'D:\yolo26s_platform\storage\uploads')
for r in rows:
    p = upload / r[2]
    if p.exists():
        TEST_IMGS.append((str(p), r[1][:30]))

def load_img(p):
    buf = np.fromfile(p, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    # 模拟生产：resize 到 2560
    if img.shape[0] != RESIZE:
        img = cv2.resize(img, (RESIZE, RESIZE), interpolation=cv2.INTER_CUBIC)
    return img


print('='*70)
print('PART 1: 速度对比（同一张崩边图，5 种格式）')
print('='*70)

img = load_img(TEST_IMGS[0][0])
print(f'测试图: {TEST_IMGS[0][1]}  shape={img.shape}')
print()

configs = [
    ('PT-CUDA',  PT,   'cuda:0',  'pytorch'),
    ('PT-CPU',   PT,   'cpu',     'pytorch'),
    ('OV-CPU',   OV,   'CPU',     'openvino'),
    ('OV-GPU.0', OV,   'GPU.0',   'openvino'),
    ('ONNX-CPU', ONNX, 'cpu',     'onnx'),
]
print(f'{"config":<12} {"best_ms":<10} {"per_crop":<10} {"n_det":<6}')
print('-' * 50)
speed_results = {}
for label, path, dev, kind in configs:
    if kind == 'pytorch':
        m = YOLO(path)
        if 'cuda' in dev: m.to(dev)
        m._model_type = 'pytorch'
    else:
        m = YOLO(path, task='segment'); m._model_type = kind
    # 预热
    _ = infer_single_image(m, img, crop_size=CROP_SIZE, overlap=OVERLAP, conf_thresh=0.15, iou_thresh=0.5,
                            use_morphology=True, dilate_kernel=MORPH_KERNEL, erode_kernel=MORPH_KERNEL, device=dev)
    ts = []
    for _ in range(3):
        t0 = time.time()
        r = infer_single_image(m, img, crop_size=CROP_SIZE, overlap=OVERLAP, conf_thresh=0.15, iou_thresh=0.5,
                                use_morphology=True, dilate_kernel=MORPH_KERNEL, erode_kernel=MORPH_KERNEL, device=dev)
        ts.append(time.time() - t0)
    best = min(ts) * 1000
    n_crops = 25  # 5×5
    speed_results[label] = (best, r)
    print(f'{label:<12} {best:>7.0f}ms  {best/n_crops:>6.1f}ms   n={r["num_detections"]}')

print()
print('='*70)
print('PART 2: 一致性对比（4 种 format 在 3 张崩边图上检出）')
print('='*70)

m_pt   = YOLO(PT); m_pt.to('cuda:0'); m_pt._model_type='pytorch'
m_ovc  = YOLO(OV, task='segment'); m_ovc._model_type='openvino'
m_ovg  = YOLO(OV, task='segment'); m_ovg._model_type='openvino'
m_onnx = YOLO(ONNX, task='segment'); m_onnx._model_type='onnx'

for path, name in TEST_IMGS:
    img = load_img(path)
    print(f'\n--- {name} ---')
    def cnt_by_class(r):
        c = r['classes'].tolist() if hasattr(r['classes'], 'tolist') else list(r['classes'])
        return {0: c.count(0), 1: c.count(1), 2: c.count(2)}

    for label, m, dev in [('PT_CUDA', m_pt, 'cuda:0'),
                          ('OV_CPU ', m_ovc, 'CPU'),
                          ('OV_GPU0', m_ovg, 'GPU.0'),
                          ('ONNX   ', m_onnx, 'cpu')]:
        r = infer_single_image(m, img, crop_size=CROP_SIZE, overlap=OVERLAP, conf_thresh=0.15, iou_thresh=0.5,
                                use_morphology=True, dilate_kernel=MORPH_KERNEL, erode_kernel=MORPH_KERNEL, device=dev)
        c = cnt_by_class(r)
        sc = sorted(r['scores'].tolist(), reverse=True)[:5] if r['num_detections'] > 0 else []
        print(f'  {label}: n={r["num_detections"]:>2}  隐裂={c[0]} 崩边={c[1]} 缺口={c[2]}  top={[round(s,3) for s in sc]}')

print()
print('='*70)
print('PART 3: 崩边检出召回率（用 conf=0.05 看是否能识别）')
print('='*70)
print('（YOLO11n 整体置信度低，conf=0.05 看真实召回能力）')
for path, name in TEST_IMGS:
    img = load_img(path)
    r = infer_single_image(m_pt, img, crop_size=CROP_SIZE, overlap=OVERLAP, conf_thresh=0.05, iou_thresh=0.5,
                            use_morphology=True, dilate_kernel=MORPH_KERNEL, erode_kernel=MORPH_KERNEL, device='cuda:0')
    c = cnt_by_class(r)
    cls_arr = r['classes'].tolist() if hasattr(r['classes'], 'tolist') else list(r['classes'])
    bb_scores = [s for s, k in zip(r['scores'], cls_arr) if k == 1]
    print(f'\n{name}: n_total={r["num_detections"]} 隐裂={c[0]} 崩边={c[1]} 缺口={c[2]}')
    if bb_scores:
        print(f'  崩边 conf: {[round(s,3) for s in sorted(bb_scores, reverse=True)]}')
