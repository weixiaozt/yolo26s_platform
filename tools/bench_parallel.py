# -*- coding: utf-8 -*-
"""验证 CPU + 核显并发推理是否真正物理隔离不竞争"""
import sys, time, threading
import numpy as np
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')
from core.inference import infer_single_image
from ultralytics import YOLO
import cv2

OV = r'D:\yolo26s_platform\storage\runs\task_52\runs\train\weights\best_openvino_model'
SRC1 = r'D:\yolo26s_platform\storage\uploads\35\009cdf26_6717383.bmp'
SRC2 = r'D:\yolo26s_platform\storage\uploads\35\01d32107_划伤_7_56_9_443.bmp'

def load(p):
    buf = np.fromfile(p, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img.ndim == 2: img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return cv2.resize(img, (2560, 2560), interpolation=cv2.INTER_CUBIC)

img1 = load(SRC1)
img2 = load(SRC2)

# 两个独立 model 实例（模拟两路相机用不同 device）
m_cpu = YOLO(OV, task='segment'); m_cpu._model_type='openvino'
m_gpu = YOLO(OV, task='segment'); m_gpu._model_type='openvino'

# 预热（让 OV 编译模型到对应 device）
print('预热...')
_ = infer_single_image(m_cpu, img1, crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.5,
                       use_morphology=True, dilate_kernel=3, erode_kernel=3, device='CPU')
_ = infer_single_image(m_gpu, img2, crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.5,
                       use_morphology=True, dilate_kernel=3, erode_kernel=3, device='GPU.0')

results = {}
def run(label, m, dev, img):
    t0 = time.time()
    r = infer_single_image(m, img, crop_size=640, overlap=0.2, conf_thresh=0.15, iou_thresh=0.5,
                           use_morphology=True, dilate_kernel=3, erode_kernel=3, device=dev)
    results[label] = (time.time() - t0, r['num_detections'])

print()
print('='*60)
print('单跑（baseline）')
print('='*60)
for i in range(3):
    run(f'cpu_solo_{i}', m_cpu, 'CPU', img1)
    run(f'gpu_solo_{i}', m_gpu, 'GPU.0', img2)
cpu_solo = min(results[f'cpu_solo_{i}'][0] for i in range(3))
gpu_solo = min(results[f'gpu_solo_{i}'][0] for i in range(3))
print(f'CPU   单跑: {cpu_solo*1000:.0f}ms')
print(f'GPU.0 单跑: {gpu_solo*1000:.0f}ms')

print()
print('='*60)
print('并发（CPU + GPU.0 同时启动）')
print('='*60)
# 多轮取 best
par_cpu_times = []
par_gpu_times = []
par_wall_times = []
for i in range(3):
    t_wall = time.time()
    t1 = threading.Thread(target=run, args=(f'cpu_par_{i}', m_cpu, 'CPU', img1))
    t2 = threading.Thread(target=run, args=(f'gpu_par_{i}', m_gpu, 'GPU.0', img2))
    t1.start(); t2.start()
    t1.join(); t2.join()
    wall = time.time() - t_wall
    par_cpu_times.append(results[f'cpu_par_{i}'][0])
    par_gpu_times.append(results[f'gpu_par_{i}'][0])
    par_wall_times.append(wall)

par_cpu = min(par_cpu_times)
par_gpu = min(par_gpu_times)
par_wall = min(par_wall_times)
print(f'CPU   并发: {par_cpu*1000:.0f}ms  (单跑 {cpu_solo*1000:.0f}ms, 慢 {(par_cpu-cpu_solo)/cpu_solo*100:+.0f}%)')
print(f'GPU.0 并发: {par_gpu*1000:.0f}ms  (单跑 {gpu_solo*1000:.0f}ms, 慢 {(par_gpu-gpu_solo)/gpu_solo*100:+.0f}%)')
print(f'两路 wall: {par_wall*1000:.0f}ms')
print()

print(f'串行总时（baseline）: {(cpu_solo + gpu_solo)*1000:.0f}ms')
print(f'并发总时（实测） : {par_wall*1000:.0f}ms')
print(f'并发节省 {(1 - par_wall/(cpu_solo + gpu_solo))*100:.0f}%（理想 50% = 完全隔离不竞争）')
