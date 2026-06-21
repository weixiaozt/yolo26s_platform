# -*- coding: utf-8 -*-
"""试 task 58 模型加 nms=True 重新导出 OpenVINO，验证 ultralytics 是否给 seg 模型包装 NMS 节点"""
import sys, os, shutil, time
from pathlib import Path

# OpenVINO 2026+ 兼容
import openvino as ov
sys.modules['openvino.runtime'] = ov

SRC = Path(r"D:\yolo26s_platform\storage\runs\task_58\runs\train\weights\best.pt")
OUT_DIR = Path(r"D:\yolo26s_platform\tools\_test_export_nms_out")

if OUT_DIR.exists():
    shutil.rmtree(OUT_DIR)
OUT_DIR.mkdir(parents=True)

# 复制 best.pt 到独立目录避免污染原始导出
work_pt = OUT_DIR / "best.pt"
shutil.copy2(SRC, work_pt)

from ultralytics import YOLO

print(f"[1/3] 加载模型: {work_pt}")
m = YOLO(str(work_pt))
print(f"      task = {m.task}")
print(f"      模型 head end2end (property) = {getattr(m.model.model[-1], 'end2end', 'N/A')}")
print(f"      模型 head _end2end (raw)     = {getattr(m.model.model[-1], '_end2end', 'N/A')}")
print(f"      head has one2one             = {hasattr(m.model.model[-1], 'one2one')}")

print("\n[2/3] 导出 OpenVINO with nms=True ...")
t0 = time.time()
try:
    out_path = m.export(
        format="openvino",
        imgsz=640,
        half=False,
        nms=True,
    )
    print(f"      成功！耗时 {time.time()-t0:.1f}s")
    print(f"      导出路径: {out_path}")
except Exception as e:
    print(f"      失败: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

print("\n[3/3] 检查 OpenVINO IR 模型输入输出结构")
out_path = Path(out_path)
xml = list(out_path.glob("*.xml"))
if not xml:
    print("      未找到 .xml")
    sys.exit(1)

core = ov.Core()
ov_model = core.read_model(str(xml[0]))
print(f"\n      输入:")
for inp in ov_model.inputs:
    print(f"        {inp.get_any_name()}: {inp.get_partial_shape()} dtype={inp.get_element_type()}")
print(f"      输出:")
for o in ov_model.outputs:
    print(f"        {o.get_any_name()}: {o.get_partial_shape()} dtype={o.get_element_type()}")

# 简单推理测试：随机 tensor 喂进去看输出
import numpy as np
print("\n[4/4] 随机 tensor 推理测试 ...")
compiled = core.compile_model(ov_model, "CPU")
input_tensor = np.random.rand(1, 3, 640, 640).astype(np.float32)
result = compiled([input_tensor])
print(f"      输出 tensor 数: {len(result)}")
for i, (k, v) in enumerate(result.items()):
    print(f"        output[{i}] name={k.get_any_name() if hasattr(k,'get_any_name') else k}, shape={v.shape}, dtype={v.dtype}")
    print(f"           min={v.min():.4f} max={v.max():.4f} mean={v.mean():.4f}")
