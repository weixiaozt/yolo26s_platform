# -*- coding: utf-8 -*-
"""测试 YOLO26-seg OV 模型直接读 raw output 是否能手写 NMS 解析。
之前结论"YOLO26+OV 不可用"是基于 ultralytics 推理路径，跳过它可能能绕开。

对比：
1. PT (ultralytics) 推理 — 真值
2. OV (ultralytics) 推理 — 旧结论：conf 是 logit 错的
3. OV 直接读 raw output + 手写 sigmoid + NMS — 看能不能拿到合理结果
"""
import sys, shutil
from pathlib import Path
import openvino as ov
sys.modules['openvino.runtime'] = ov
sys.path.insert(0, r'D:\yolo26s_platform')

import numpy as np
import cv2
from ultralytics import YOLO

PT_TASK20 = Path(r"D:\yolo26s_platform\storage\runs\task_20\runs\train\weights\best.pt")
WORK_DIR  = Path(r"D:\yolo26s_platform\tools\_diag_yolo26_ov")
OV_TASK20 = WORK_DIR / "best_openvino_model"

# 如果 OV 目录不存在或不全，重新导出
if not (OV_TASK20 / "metadata.yaml").exists():
    print(f"[setup] OV 包不全，从 {PT_TASK20.name} 重新导出 ...")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    work_pt = WORK_DIR / "best.pt"
    shutil.copy2(PT_TASK20, work_pt)
    m = YOLO(str(work_pt))
    print(f"  PT 模型 task={m.task}, head end2end={getattr(m.model.model[-1], 'end2end', 'N/A')}")
    out = m.export(format="openvino", imgsz=640, half=False)
    print(f"  导出完成: {out}\n")

# 找一张 task 58 val 集的 640 crop（已知有缺陷）
IMG = Path(r"D:\yolo26s_platform\storage\runs\task_58\dataset\images\val\000604_0000_1920.png")

print(f"PT model: {PT_TASK20}")
print(f"OV model: {OV_TASK20}\n")

# 检查 OV metadata
meta = (OV_TASK20 / "metadata.yaml").read_text(encoding='utf-8')
print("[OV metadata 关键字段]")
for line in meta.splitlines():
    if any(k in line for k in ('nms:', 'end2end:', 'task:', 'imgsz:', '- 640', '- 1280')):
        print(f"  {line}")
print()

# 准备一个 640 crop（task 20 imgsz 是多少看 metadata，先按 640）
crop = cv2.imread(str(IMG))
if crop.shape[:2] != (640, 640):
    crop = cv2.resize(crop, (640, 640))
print(f"图: {IMG.name}  shape={crop.shape}\n")

# === 1) PT 推理（真值） ===
print("="*60)
print("[1] PT 推理（真值）")
print("="*60)
m_pt = YOLO(str(PT_TASK20), task='segment')
r = m_pt.predict(crop, conf=0.25, iou=0.45, verbose=False, device='cpu')[0]
if r.boxes is not None and len(r.boxes) > 0:
    print(f"  检出: {len(r.boxes)}")
    for i in range(len(r.boxes)):
        xyxy = r.boxes.xyxy[i].cpu().numpy()
        c = float(r.boxes.conf[i])
        k = int(r.boxes.cls[i])
        print(f"    cls={k} conf={c:.4f} box=({xyxy[0]:.0f},{xyxy[1]:.0f})-({xyxy[2]:.0f},{xyxy[3]:.0f})")
else:
    print("  检出: 0")
print()

# === 2) OV 推理 via ultralytics（旧路径，可能不对） ===
print("="*60)
print("[2] OV 推理 via ultralytics (旧路径)")
print("="*60)
try:
    m_ov = YOLO(str(OV_TASK20), task='segment')
    r = m_ov.predict(crop, conf=0.25, iou=0.45, verbose=False, device='intel:CPU')[0]
    if r.boxes is not None and len(r.boxes) > 0:
        print(f"  检出: {len(r.boxes)}")
        for i in range(len(r.boxes)):
            xyxy = r.boxes.xyxy[i].cpu().numpy()
            c = float(r.boxes.conf[i])
            k = int(r.boxes.cls[i])
            print(f"    cls={k} conf={c:.4f} box=({xyxy[0]:.0f},{xyxy[1]:.0f})-({xyxy[2]:.0f},{xyxy[3]:.0f})")
    else:
        print("  检出: 0")
except Exception as e:
    print(f"  失败: {e}")
print()

# === 3) OV 直接读 raw output（绕过 ultralytics） ===
print("="*60)
print("[3] OV raw output（手写解析）")
print("="*60)
core = ov.Core()
xml = list(OV_TASK20.glob("*.xml"))[0]
ov_model = core.read_model(str(xml))
def safe_name(t):
    try: return t.get_any_name()
    except Exception: return "<unnamed>"
print(f"  输入: {[(safe_name(i), i.get_partial_shape()) for i in ov_model.inputs]}")
print(f"  输出: {[(safe_name(o), o.get_partial_shape()) for o in ov_model.outputs]}")

compiled = core.compile_model(ov_model, "CPU")

# 预处理：640×640 RGB float32 / 255
inp = cv2.resize(crop, (640, 640))
inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
inp = inp.transpose(2, 0, 1)[None].astype(np.float32) / 255.0

result = compiled([inp])
outs = list(result.values())
print(f"\n  推理后输出 tensor 数: {len(outs)}")
for i, o in enumerate(outs):
    print(f"    out[{i}] shape={o.shape}  dtype={o.dtype}")
    print(f"       min={o.min():.4f}  max={o.max():.4f}  mean={o.mean():.4f}")

# 分析 output[0]：通常是检测主输出
# YOLO11/26 seg：output[0] = (1, 4+nc+nm, 8400) 或 end2end (1, 300, 6+nm)
# 拿主 head 看 conf 数值范围
main_out = outs[0]
print(f"\n  主 output 分析 (shape={main_out.shape}):")

if len(main_out.shape) == 3 and main_out.shape[1] < main_out.shape[2]:
    # (1, C, N) 格式：分割 4 (bbox) + nc (class) + nm (mask coeff)
    nc_guess = main_out.shape[1] - 4 - 32  # 假设 nm=32
    print(f"  推测格式: (1, 4+nc+nm, N) = (1, 4+{nc_guess}+32, {main_out.shape[2]})")
    # 取 class scores 部分 (索引 4 : 4+nc)
    cls_scores = main_out[0, 4:4+nc_guess, :]
    print(f"  class scores 区间: min={cls_scores.min():.4f}  max={cls_scores.max():.4f}")
    print(f"    → 如果 max > 1，原始 conf 是 logit（要 sigmoid）")
    print(f"    → 如果 0 ≤ all ≤ 1，已经是 prob（不用 sigmoid）")

    # 取每个 anchor 的 max class score
    per_anchor_max = cls_scores.max(axis=0)
    print(f"  per-anchor max class score: min={per_anchor_max.min():.4f}  max={per_anchor_max.max():.4f}")

    # 应用 sigmoid 看分布
    def sigmoid(x): return 1 / (1 + np.exp(-x))
    after_sig = sigmoid(per_anchor_max)
    print(f"  sigmoid 后: min={after_sig.min():.4f}  max={after_sig.max():.4f}")
    # 看 conf > 0.25 的有几个
    n_kept = (after_sig > 0.25).sum()
    print(f"  sigmoid(score) > 0.25 的 anchor 数: {n_kept}")

elif len(main_out.shape) == 3 and main_out.shape[1] == 300:
    print(f"  推测格式: end2end (1, 300, 6+nm) 已 NMS 过滤")
    # 38 = 4 (xyxy) + 1 (conf) + 1 (cls) + 32 (mask coeff)
    boxes = main_out[0, :, 0:4]
    confs = main_out[0, :, 4]
    classes = main_out[0, :, 5]
    print(f"  xyxy 区间: min={boxes.min():.3f}  max={boxes.max():.3f}")
    print(f"  conf 字段: min={confs.min():.4f}  max={confs.max():.4f}  → 是 prob (0-1) 还是 logit?")
    print(f"  cls 字段:  min={classes.min():.1f}  max={classes.max():.1f}")
    print()
    print("  Top-5 by conf (raw read，无需 sigmoid):")
    top5 = np.argsort(-confs)[:5]
    for i in top5:
        b = boxes[i]
        print(f"    conf={confs[i]:.4f} cls={int(classes[i])} box=({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f})")
    print()
    print(f"  conf > 0.25 的 box 数: {(confs > 0.25).sum()}")
    print(f"  conf > 0.10 的 box 数: {(confs > 0.10).sum()}")
    print()
    print("  → 结论：")
    print("    - 如果 max conf ≤ 1 且 top-k 数值合理 → 已 sigmoid，同事可直接用")
    print("    - 如果 max conf > 1 → 是 logit，同事需要先 sigmoid 再过滤")
