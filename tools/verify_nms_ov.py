# -*- coding: utf-8 -*-
"""真实图验证：对比旧 OV (nms=False) 与新 OV (nms=True) 在 task 58 val 集上的检测一致性

成功标准：
  - 新 OV 能正确推理，输出 box/mask
  - 与旧 OV 相比 box 数量近似，重合度高
  - cls/conf 分布一致
"""
import sys, os
from pathlib import Path

# OpenVINO 2026+ 兼容
import openvino as ov
sys.modules['openvino.runtime'] = ov

import numpy as np
import cv2
from ultralytics import YOLO

OLD_OV = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best_openvino_model")
NEW_OV = Path(r"D:\yolo26s_platform\tools\_test_export_nms_out\best_openvino_model")
VAL_DIR = Path(r"D:\yolo26s_platform\storage\runs\task_58\dataset\images\val")

# 取一批 val 图（含有标注的更好，但 val 集大概率都有缺陷）
imgs = sorted(VAL_DIR.glob("*.png"))[:10]
print(f"测试图数：{len(imgs)}")
print(f"旧 OV：{OLD_OV}")
print(f"新 OV：{NEW_OV}")

print("\n[1] 加载两个模型...")
m_old = YOLO(str(OLD_OV), task='segment')
m_new = YOLO(str(NEW_OV), task='segment')

# 用一致的推理参数
CONF, IOU = 0.25, 0.5

def iou_xyxy(b1, b2):
    x1, y1, x2, y2 = max(b1[0],b2[0]), max(b1[1],b2[1]), min(b1[2],b2[2]), min(b1[3],b2[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    a1 = (b1[2]-b1[0]) * (b1[3]-b1[1])
    a2 = (b2[2]-b2[0]) * (b2[3]-b2[1])
    return inter / max(1e-6, a1+a2-inter)

def match(boxes_a, boxes_b, cls_a, cls_b, thr=0.5):
    """返回 (匹配对数, 仅 a 独有, 仅 b 独有)"""
    if len(boxes_a) == 0 and len(boxes_b) == 0: return 0, 0, 0
    used_b = set(); matched = 0
    for i, ba in enumerate(boxes_a):
        best, best_j = 0, -1
        for j, bb in enumerate(boxes_b):
            if j in used_b: continue
            if cls_a[i] != cls_b[j]: continue
            v = iou_xyxy(ba, bb)
            if v > best: best, best_j = v, j
        if best >= thr:
            matched += 1; used_b.add(best_j)
    return matched, len(boxes_a)-matched, len(boxes_b)-matched

print("\n[2] 逐图比对（device=CPU）...")
print(f"{'图':<32} {'旧#':>4} {'新#':>4} {'匹配':>4} {'仅旧':>4} {'仅新':>4} {'平均IoU':>8}")
print("-"*72)

stats = {'tot_old': 0, 'tot_new': 0, 'tot_match': 0, 'tot_only_old': 0, 'tot_only_new': 0, 'ious': []}
for p in imgs:
    img = cv2.imread(str(p))
    r_old = m_old.predict(img, conf=CONF, iou=IOU, device='intel:CPU', verbose=False)[0]
    r_new = m_new.predict(img, conf=CONF, iou=IOU, device='intel:CPU', verbose=False)[0]

    b_old = r_old.boxes.xyxy.cpu().numpy() if r_old.boxes is not None else np.zeros((0,4))
    b_new = r_new.boxes.xyxy.cpu().numpy() if r_new.boxes is not None else np.zeros((0,4))
    c_old = r_old.boxes.cls.cpu().numpy().astype(int) if r_old.boxes is not None else np.array([])
    c_new = r_new.boxes.cls.cpu().numpy().astype(int) if r_new.boxes is not None else np.array([])

    m_cnt, only_old, only_new = match(b_old, b_new, c_old, c_new, thr=0.5)
    # 平均 IoU（对匹配上的对）
    ious = []
    used_b = set()
    for i, ba in enumerate(b_old):
        best, best_j = 0, -1
        for j, bb in enumerate(b_new):
            if j in used_b: continue
            if c_old[i] != c_new[j]: continue
            v = iou_xyxy(ba, bb)
            if v > best: best, best_j = v, j
        if best >= 0.5:
            ious.append(best); used_b.add(best_j)
    avg_iou = np.mean(ious) if ious else 0.0

    print(f"{p.name:<32} {len(b_old):>4} {len(b_new):>4} {m_cnt:>4} {only_old:>4} {only_new:>4} {avg_iou:>8.3f}")
    stats['tot_old'] += len(b_old); stats['tot_new'] += len(b_new)
    stats['tot_match'] += m_cnt; stats['tot_only_old'] += only_old; stats['tot_only_new'] += only_new
    stats['ious'].extend(ious)

print("-"*72)
print(f"{'合计':<32} {stats['tot_old']:>4} {stats['tot_new']:>4} {stats['tot_match']:>4} {stats['tot_only_old']:>4} {stats['tot_only_new']:>4} {np.mean(stats['ious']) if stats['ious'] else 0:>8.3f}")

# 关键诊断
print()
print("=" * 60)
print("结论")
print("=" * 60)
recall = stats['tot_match'] / max(1, stats['tot_old'])
precision = stats['tot_match'] / max(1, stats['tot_new'])
mean_iou = float(np.mean(stats['ious'])) if stats['ious'] else 0.0

print(f"召回（旧 box 被新 OV 找到的比例）: {recall*100:.1f}%")
print(f"精度（新 box 在旧 OV 中存在的比例）: {precision*100:.1f}%")
print(f"匹配 box 平均 IoU: {mean_iou:.3f}")

if recall >= 0.9 and precision >= 0.9 and mean_iou >= 0.85:
    print("\n  PASS: 新 OV 与旧 OV 行为一致，方案 B 可用")
elif stats['tot_new'] == 0 and stats['tot_old'] > 0:
    print("\n  FAIL: 新 OV 没有任何输出，NMS 节点可能解析错")
else:
    print("\n  PARTIAL: 行为接近但有偏差，需人工检查具体差异")

# 检查 mask 也能拿到
print()
print("[3] mask 抽样检查")
img0 = cv2.imread(str(imgs[0]))
r_new = m_new.predict(img0, conf=CONF, iou=IOU, device='intel:CPU', verbose=False)[0]
if r_new.masks is not None:
    print(f"  mask shape: {r_new.masks.data.shape}, count: {len(r_new.masks)}")
else:
    print("  mask is None")
