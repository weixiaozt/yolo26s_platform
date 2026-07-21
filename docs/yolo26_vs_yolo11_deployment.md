# YOLO26-seg vs YOLO11-seg 部署选型与避坑

> 适用：从训练到 OpenVINO 部署，需要在 YOLO11-seg 和 YOLO26-seg 之间选型
> 写于：2026-06-21
> 关键结论：**YOLO26-seg + OpenVINO 实测可用**（之前"不可修复"的判断已更正），但与 YOLO11-seg 在导出和部署上存在**架构级差异**，盲目切换会踩坑

---

## 1. 重要前置说明

YOLO26-seg 和 YOLO11-seg 在 ultralytics 里走的是**两条不同的 head 架构**，导出格式也不一样。

| 维度 | YOLO11-seg | YOLO26-seg |
|---|---|---|
| `head.end2end` 默认值 | **False** | **True** |
| 训练方式 | 经典 one2many + 后处理 NMS | **NMS-free**（one2one 分支 + TopK） |
| `model.export()` 默认输出 shape | `(1, 4+nc+nm, 8400)` 原始候选 | `(1, 300, 6+nm)` **已筛选结果** |
| 需不需要单图传统 NMS | **需要** | **不需要**（不是 graph 内嵌传统 NMS）|
| 模型文件大小 (n 系列) | YOLO11n-seg ~5.8MB | YOLO26s-seg ~22MB（n 暂无） |

**这意味着同一份部署代码不能直接换模型** —— 切换 YOLO11→YOLO26 必须改后处理逻辑。

---

## 1.5 概念补充：什么是 end-to-end 架构

理解后面所有内容的前提。

### end2end = "端到端"，指 one-to-one head 直接产生 NMS-free 结果

YOLO 检测的完整流水线：

```
图 → 神经网络 forward → 后处理 NMS → 最终 box 列表
```

- **end2end=False**（YOLO11 默认）：模型只负责"forward"，**NMS 必须外部做**
- **end2end=True**（YOLO10 / YOLO26 默认）：one-to-one 分配让结果不再依赖传统 IoU NMS，并通过 TopK 输出最终候选

### 核心区别：训练时每个目标用几个 anchor

YOLO 把图划分成网格，每个格子有一组 anchor box。训练时要决定：**每个 ground truth bbox 由哪些 anchor 负责学习？**

**end2end=False（经典 YOLO，one2many）**

```
一个 GT bbox（猫脸）的训练分配：

      ┌──────────────────────────┐
      │  猫脸 GT 框                │
      │   ┌─[anchor1]─┐  ← 强匹配  │
      │   │ ┌─[a2]──┐ │  ← 强匹配  │
      │   │ │ ┌─[a3]┐│ │  ← 弱匹配  │
      │   │ │ │     ││ │  ← 弱匹配  │
      │   │ │ └─────┘│ │           │
      │   │ └────────┘ │           │
      │   └────────────┘           │
      └──────────────────────────┘

  → 4 个 anchor 都算 loss（梯度信号丰富，容易收敛）
  → 推理时这 4 个 anchor 都"觉得这里有猫"，全部输出
  → 必须用 NMS（IoU > 0.5 合并）压成 1 个
```

**end2end=True（YOLO10/26，one2many + one2one 双 head）**

模型同时长**两个 head**，并行训练：

```
backbone → FPN/PAN ──┬─→ one2many head  (训练用，给丰富梯度)
                     │
                     └─→ one2one head   (训练 + 推理都用)
                          ↑
                  匈牙利算法强制：每个 GT 只挑 1 个最佳 anchor
                  其他 anchor 在这个位置上被监督"输出空"

  → 一个 GT 只让 1 个 anchor 学
  → 推理时只有那 1 个 anchor 输出"猫"，其他 anchor 学到了"不要响应"
  → 输出本身就无重叠，NMS 不需要
```

**关键点**：`one2many` head 只在训练阶段帮助梯度收敛，**推理时被完全丢弃**。模型最终用 `one2one` head 的输出。

### 对部署的具体影响

| 维度 | end2end=False (YOLO11) | end2end=True (YOLO26) |
|---|---|---|
| 模型权重大小 | 基础大小 | 多一份 head（约 +20%）|
| 推理 forward 时间 | 标准 | 略慢（多一个 head 计算，但被丢弃）|
| **单图传统 NMS 是否必需** | **必需**，自己写或内嵌到导出图 | **不需要** |
| 输出 shape | `(1, 4+nc+nm, 8400)` 原始候选 | `(1, 300, 6+nm)` one-to-one + TopK |
| **延迟（含后处理）** | forward + NMS（CPU 上 NMS ~2-10ms）| forward + TopK |
| 阈值调整 | conf/iou 均可调 | conf 可事后过滤，没有传统 NMS 的 iou 阈值 |
| 边缘 case 行为 | 可调 NMS 阈值找回 / 抑制 | 可改用 `end2end=False` 的兼容模式 |

### 形象比喻

- **end2end=False = "粗放生产线"**：每个工人看到目标都汇报（你"猫"我也"猫"），最后质检员（NMS）合并重复汇报
- **end2end=True = "精细生产线"**：训练时就严格规定"每个目标只能 1 个工人负责"，直接出最终结果，没有质检环节

### 这跟选模型的关系

- 如果你的部署代码本来就有一套现成的 NMS → **YOLO11** 或 YOLO26 `end2end=False` 更自然
- 如果你希望部署代码越简单越好 → YOLO26 原生模式直接输出已筛选结果
- 如果你想精细控制 NMS 行为 → 使用 YOLO11，或把 YOLO26 切到兼容模式
- 如果只是想要标准 NMS 行为、性能优先 → 两者都行，看模型大小和精度

---

## 2. 实测验证（2026-06-21）

用 task 20（YOLO26s-seg）的 best.pt 重新导出 OV，单 640×640 crop 推理：

```
[1] PT (ultralytics):    cls=0 conf=0.4809 box=(427,400)-(434,413)
[2] OV via ultralytics:  cls=0 conf=0.4809 box=(427,400)-(434,413)   ← 完全一致
[3] OV raw output[0]:    shape=(1, 300, 38), conf 字段 max=0.4809（0-1 prob）
```

**ultralytics 8.4.33 + OpenVINO 2026.1.0 组合下**：
- PT 与 OV via ultralytics 输出 conf 完全一致（4 位小数）
- OV 原始输出的 conf 字段已经是 sigmoid 后的 prob，**不是 logit**
- 早期"YOLO26+OV conf 变 logit 不可修复"的结论已不成立

验证脚本：`tools/diag_yolo26_ov_raw.py`，可直接复现。

---

## 3. YOLO26-seg OV 模型输出格式详解

```
output[0]: shape (1, 300, 38)        ← 端到端 NMS 已跑过
output[1]: shape (1, 32, 160, 160)   ← mask 原型 (与 YOLO11 相同)
```

第三维 38 个值的含义（按顺序）：

| 索引 | 含义 |
|---|---|
| `[0:4]` | `[x1, y1, x2, y2]` 框坐标，绝对像素（对应导出时 imgsz=640） |
| `[4]` | `conf` 置信度，已 sigmoid，**直接使用** |
| `[5]` | `cls` 类别 id（0=隐裂, 1=崩边, 2=缺口 — 项目 8） |
| `[6:38]` | `mask_coeff × 32` mask 系数，与 output[1] 矩阵乘解码 mask |

**注意**：output[0] 一共 300 个槽位是固定的（max_det 默认 300）。**有效 box 数远少于 300**，剩下的是 padding：
- 有效 box：conf 通常 > 0.01
- padding 槽：conf 接近 0，bbox 字段可能是负数

部署端用一行 filter：
```python
valid = detections[0][:, 4] > YOUR_CONF_THRESHOLD  # 比如 0.25 或 0.15
real_dets = detections[0][valid]
```

---

## 4. 避坑指南（部署端必看）

### ❌ 坑 1：保持 `end2end=True` 时直接追加 `nms=True`

```python
# 错误做法
model = YOLO('yolo26s-seg-best.pt')
model.export(format='openvino', end2end=True, nms=True)  # ← 模式冲突
```

YOLO26 原生模式是 one-to-one NMS-free，不应直接叠加传统 NMS。平台现在提供两种互斥的正确模式：

```python
# 原生模式：速度和部署简单优先
model.export(format='openvino', end2end=True, nms=False)

# 兼容/高召回模式：导出 one-to-many 原始候选，由运行时统一做 NMS
model.export(format='openvino', end2end=False, nms=False)
```

YOLO11-seg 保持既有 `nms=True/False` 选项，不受 YOLO26 模式影响。

### ❌ 坑 2：把 YOLO26 当 YOLO11 用，再做一次 NMS

```python
# 错误做法（同事的旧 NMS 代码移植过来）
detections = ov_model.infer(image)[0]      # YOLO26 原生 NMS-free 输出
boxes_after_nms = my_nms(detections, iou=0.45)  # ← 重做 NMS 是无效操作
```

原生 one-to-one 输出不需要再做单图传统 NMS。注意：平台滑窗推理中，不同切片之间仍可能产生重复框，因此拼回整图后的跨切片 NMS 必须保留。

**正确做法**：
```python
detections = ov_model.infer(image)[0]      # (1, 300, 38)
valid = detections[0][:, 4] > 0.25         # 自己设 conf 阈值
result = detections[0][valid]              # 直接用
```

### ❌ 坑 3：输出 tensor 当成 YOLO11 的 (1, 4+nc+nm, 8400) 解析

YOLO11 默认输出是 `(batch, channels=4+nc+nm, anchors=8400)` —— **channels 在第 1 维**。
YOLO26 end2end 输出是 `(batch, 300, 38)` —— **每个 box 在第 1 维**。

```python
# YOLO11 解析（transpose 后切片）
out11 = output.squeeze(0).T   # (8400, 4+nc+nm)
conf = out11[:, 4]

# YOLO26 解析（不用 transpose）
out26 = output.squeeze(0)     # (300, 38)
conf = out26[:, 4]
```

错把 YOLO26 当 YOLO11 解析会把 conf 字段切到错的位置，conf 值全乱。

### ❌ 坑 4：mask 解码忽略 mask_coeff 的位置变化

YOLO11 nms=false 时 mask_coeff 是 `output[0][4+nc : 4+nc+nm]`（按 channels 切）。
YOLO26 end2end 时 mask_coeff 是 `output[0][i, 6:38]`（按 box 切，每个 box 32 维）。

`output[1]` 的 mask 原型 shape 都是 `(1, 32, 160, 160)`，二者一致。

mask 解码：
```python
# 对一个 box i
mask_coeff = detections[0][i, 6:38]                    # (32,)
proto = output[1][0]                                    # (32, 160, 160)
mask = (mask_coeff @ proto.reshape(32, -1)).reshape(160, 160)
mask = sigmoid(mask) > 0.5
mask = cv2.resize(mask.astype(np.uint8), (640, 640))   # resize 回输入尺寸
# 再按 bbox 区域裁剪
```

### ⚠️ 坑 5：模型大小翻 4 倍，推理速度会变慢

| 模型 | 大小 | YOLO26 没有 nano 系列，只有 s/m/l |
|---|---|---|
| YOLO11n-seg | 5.8MB | 最小，CPU/iGPU 推理最快 |
| YOLO11s-seg | ~10MB | 小 |
| **YOLO26s-seg** | **22MB** | 是 YOLO11n 的 ~4 倍 |

i7+UHD 集显单帧推理上，YOLO26s 比 YOLO11n 慢估计 1.5~2 倍（未实测，仅参考）。**要在精度提升和速度损失之间权衡**。

---

## 5. 选型建议

| 场景 | 推荐 |
|---|---|
| 平台默认，全部新项目 | **YOLO11n-seg** — 小、快、跨平台一致性好 |
| 部署到 i7+UHD 集显，1拖2 双相机 | **YOLO11n-seg** — 800ms 预算下更稳 |
| 精度要求很高、速度有富余 | **YOLO26s-seg** — 架构更新，mAP 上限通常更高 |
| 想直接得到筛选后的固定形状输出 | YOLO26 原生模式，或 YOLO11 用 `nms=True` 导出 |
| 小缺陷召回优先、规避端到端导出兼容问题 | **YOLO26 兼容模式：`end2end=False, nms=False`，运行时统一 NMS** |
| 想自己写 NMS / 自定义后处理 | YOLO11，或 YOLO26 `end2end=False, nms=False` |

**保守做法**：先把现有 YOLO11n-seg 部署跑稳，验证业务指标达标；然后用相同数据训一份 YOLO26s-seg 对比 mAP 和速度，再决定要不要切。

---

## 6. 部署端代码示例（YOLO26 OV）

### Python (OpenVINO Runtime)

```python
import openvino as ov
import numpy as np
import cv2

def sigmoid(x):
    return 1 / (1 + np.exp(-x))

core = ov.Core()
model = core.read_model("best.xml")
compiled = core.compile_model(model, "CPU")  # 或 "GPU.0"

img = cv2.imread("test.bmp")
img_resized = cv2.resize(img, (640, 640))
img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
input_tensor = img_rgb.transpose(2, 0, 1)[None].astype(np.float32) / 255.0

result = compiled([input_tensor])
outputs = list(result.values())
detections = outputs[0]   # (1, 300, 38)
proto = outputs[1]        # (1, 32, 160, 160)

CONF_THRESHOLD = 0.25
for i in range(detections.shape[1]):
    det = detections[0, i]
    conf = det[4]
    if conf < CONF_THRESHOLD:
        continue
    x1, y1, x2, y2 = det[0:4].astype(int)
    cls = int(det[5])
    mask_coeff = det[6:38]

    # mask 解码（可选，只要 bbox 就跳过）
    proto_flat = proto[0].reshape(32, -1)            # (32, 160*160)
    mask = (mask_coeff @ proto_flat).reshape(160, 160)
    mask = sigmoid(mask) > 0.5
    mask = cv2.resize(mask.astype(np.uint8) * 255, (640, 640))
    mask_in_box = mask[y1:y2, x1:x2]

    print(f"cls={cls} conf={conf:.3f} box=({x1},{y1})-({x2},{y2}) mask_area={mask_in_box.sum()//255}")
```

### C++ (OpenVINO Runtime)

```cpp
#include <openvino/openvino.hpp>

ov::Core core;
auto compiled = core.compile_model("best.xml", "CPU");
auto infer_req = compiled.create_infer_request();
infer_req.set_input_tensor(input_tensor);
infer_req.infer();

auto detections = infer_req.get_output_tensor(0);   // shape: {1, 300, 38}
auto proto      = infer_req.get_output_tensor(1);   // shape: {1, 32, 160, 160}

const float* data = detections.data<float>();
constexpr float CONF_THRESHOLD = 0.25f;
for (int i = 0; i < 300; ++i) {
    const float* det = data + i * 38;
    float conf = det[4];
    if (conf < CONF_THRESHOLD) continue;
    float x1 = det[0], y1 = det[1], x2 = det[2], y2 = det[3];
    int   cls = static_cast<int>(det[5]);
    // det + 6 起 32 个 mask_coeff，可与 proto 矩阵乘解码 mask
}
```

---

## 7. 测试 / 验证脚本

平台侧留了几个诊断脚本，同事如果对部署行为有疑问可直接跑：

| 脚本 | 用途 |
|---|---|
| `tools/diag_yolo26_ov_raw.py` | YOLO26 OV raw output 解析验证（conf 是 prob 不是 logit）|
| `tools/diag_pt_ov_devices.py` | 单图 5 后端对比（PT-CUDA/CPU + OV-CPU/iGPU/dGPU），看一致性 |
| `tools/bench_pt_vs_ov_multi.py` | 20 张图批量统计 CUDA vs OV 检出一致率 |

需要时联系平台侧，从 `D:\yolo26s_platform\tools\` 取脚本，改一下模型路径就能跑。

---

## TL;DR

1. **YOLO26-seg + OV 实测可用**，conf 是正常 prob，跟 PT 推理完全一致
2. **YOLO26 原生模式是 one-to-one NMS-free + TopK**，不是 graph 内执行传统 NMS
3. **小缺陷 OpenVINO 推荐兼容模式**：`end2end=False, nms=False`，由运行时统一 NMS
4. **YOLO11 继续使用原有导出/NMS链路**，不受 YOLO26 兼容模式影响
5. **跨滑窗切片的全局 NMS 仍必须保留**
