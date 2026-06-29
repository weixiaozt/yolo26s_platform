# 切割小图（crop-defects）功能逻辑

> 适用：仅 seg（实例分割）项目
> 用途：把推理检出的所有缺陷裁出小图，按类别打成 zip，**直接当作二级分类模型（yolo*-cls）的训练集**
> 写于：2026-06-23

---

## 1. 概述

在线推理页面右上角的"切割小图"按钮触发。流程：

```
推理跑一批图（DB 留下 InferenceResult + 每张图的 detections[]）
        ↓
点"切割小图" → 遍历所有推理记录 → 按 bbox 把缺陷裁出来 → 按类别打 zip → 下载
        ↓
解压后：每个类别一个文件夹，可直接喂 yolo*-cls.pt 训练二级分类模型
```

**为什么要二级分类**：一级 seg 模型负责定位（"这里有缺陷"），二级 cls 模型负责精确分类（"这个缺陷是隐裂还是崩边还是缺口"）。两级模型对工业 EL/AOI 检测精度提升明显。

---

## 2. 端到端链路

### 2.1 前端入口

[web/src/views/InferenceView.vue:46-51](web/src/views/InferenceView.vue:46) — 顶部工具栏按钮，**仅 seg 项目可见**：

```vue
<el-button v-if="projectTaskType==='seg'" type="warning" size="small"
  :disabled="history.length===0 || cropping" :loading="cropping"
  @click="cropDefects">
  <el-icon><Scissor /></el-icon> 切割小图
</el-button>
```

[web/src/views/InferenceView.vue:606-654](web/src/views/InferenceView.vue:606) `cropDefects()` 逻辑：

1. 弹 ElMessageBox 确认（说明规则 + 用途）
2. POST `/api/inference/crop-defects?project_id=<id>`，`responseType: 'blob'`，timeout 10 分钟
3. 拿到 blob → 检查 content-type 是不是 `zip`（错误响应也是 blob，要 parse 出 detail）
4. 用 `URL.createObjectURL` + 隐藏 `<a download>` 触发浏览器下载
5. 显示成功提示，含 `X-Crop-Count` header 报告 crop 张数

### 2.2 后端路由

[server/routers/inference.py:774](server/routers/inference.py:774) `crop_defects_for_classifier(project_id)`：

```python
@router.post("/crop-defects")
def crop_defects_for_classifier(project_id, db):
    # 1. 校验是 seg 项目（其他 task_type 返回 400）
    if project.task_type != "seg": raise HTTPException(400, ...)

    # 2. 拿该项目所有有缺陷检出的推理记录
    records = db.query(InferenceResult).filter(
        InferenceResult.project_id == project_id
    ).all()

    # 3. 遍历每条记录
    for rec in records:
        img = cv2.imread(rec.original_path)   # 加载原图（可能是 4K）

        # 关键：把图按推理时的 resize_size 缩到推理尺寸
        # 让 img 和 bbox 落在同一坐标系里（见 §5 坑）
        if rec.resize_size > 0:
            scale = rec.resize_size / max(h, w)
            img = cv2.resize(img, (int(w*scale), int(h*scale)), cv2.INTER_CUBIC)

        # 4. 遍历每个检出的 bbox
        for det in rec.detections:
            crop, out_size = _crop_defect_for_classifier(img, det["bbox"])
            # 编码成原图扩展名（.bmp/.png/.jpg）
            ok, buf = cv2.imencode(ext, crop)
            crops.append((zip_name, buf.tobytes()))

    # 5. 全部 crop 打包成 zip 流式返回
    return StreamingResponse(zip_buffer, media_type="application/zip", ...)
```

---

## 3. 单张切图规则

[server/routers/inference.py:734](server/routers/inference.py:734) `_crop_defect_for_classifier(img, bbox, target_min=128, target_max=512)`：

按 **bbox 长边** 分三档处理：

| bbox 长边 | 切图行为 | 输出尺寸 |
|---|---|---|
| `> 512` (大缺陷) | 以 bbox 中心补正方形（取 long_edge × long_edge）→ resize 到 512×512 | **512** |
| `128 ≤ 长边 ≤ 512` (中等缺陷) | 按长边补正方形原样切（不缩放）| **=长边** |
| `< 128` (小缺陷) | 以 bbox 中心**向外膨胀**到 128×128（不缩放，多带周围上下文）| **128** |

### 边界处理

- 切窗超出图边时**往内推**保持完整正方形，避免黑边
- fallback：`side = min(side, min(W, H))` 防止微小图越界
- 起点 `x0 = max(0, min(cx - side/2, W - side))`，y 同理

### 设计动机

- **大缺陷 resize 到 512**：避免输出小图过大撑爆 zip；512 也足够二级 cls 模型 fine-tune
- **小缺陷向外膨胀**：极小缺陷（如 3×3 px）单独抠出来 cls 学不到上下文；强制 128×128 保留周围背景纹理
- **中等档不缩放**：保留原始像素，分类时纹理特征最清晰

---

## 4. zip 输出结构

```
project_<id>_crops_<count>.zip
├── 隐裂/
│   ├── 隐裂_128_0.png
│   ├── 隐裂_128_1.png
│   ├── 隐裂_286_0.png
│   ├── 隐裂_512_0.png
│   └── ...
├── 崩边/
│   ├── 崩边_128_0.png
│   └── ...
└── 缺口/
    ├── 缺口_512_0.png
    ├── 缺口_512_1.png
    └── ...
```

**命名格式**：`<类别名>/<类别名>_<输出尺寸>_<序号>.<扩展名>`

- 类别名跟 detection 里的 `class_name` 一致（来自 `_resolve_class_names`，优先用 `model.names`）
- 输出尺寸 = 上面 §3 规则的 `out_size` 字段（128 / =长边 / 512）
- 序号在 `(类别名, 输出尺寸)` 元组内独立累加，不同类别/不同尺寸互不冲突
- 扩展名跟随**原图** —— 但因为推理时 original_path 都是 png 副本，实际目前都是 `.png`

**响应 headers**：
- `Content-Disposition: attachment; filename="project_X_crops_N.zip"`
- `X-Crop-Count: N`（前端用于显示"已下载 X 张"提示）
- **没有放类别名 header**（HTTP header 限 latin-1，中文类名会炸）

---

## 5. 关键坑：bbox 坐标系（2026-06 修复）

### 问题

`InferenceResult.detections[].bbox` 存的是**推理时缩放后**坐标系（取决于 `record.resize_size`，比如长边 2560）。
但 `cv2.imread(record.original_path)` 加载的是**原图**（可能是 4K）。

如果直接用 2560 坐标的 bbox 去 crop 4K 原图：
- bbox `(852, 318)` 落在原图左上角 1/1.6 区域
- 切出来的小图**位置全错位**，根本不是缺陷

### 修复（[server/routers/inference.py:823-831](server/routers/inference.py:823)）

```python
if rec.resize_size and rec.resize_size > 0:
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side != rec.resize_size:
        scale = rec.resize_size / long_side
        img = cv2.resize(img, (int(w*scale), int(h*scale)),
                         interpolation=cv2.INTER_CUBIC)
```

**逻辑**：把原图按当时的 resize_size 也缩到推理尺寸，让 img 和 bbox 同坐标系，再用原始 bbox 直接切。这样：

- 切出的小图分辨率 = 推理时的缩放分辨率（与 mask 一致）
- bbox 不用做反向放大，避免浮点取整误差
- 想要 4K 高清小图 → **推理时不缩放**（resize_size=0），分割本身在缩放图上做，反向放大对下游 cls 没信息增益

---

## 6. 用户偏好（项目约定）

- **想要 4K 高清小图**：推理时把"长边缩放"设 0 或留空，bbox 与原图同 4K 坐标系直接切
- **想要小图节省空间**：推理时设缩放（如 2560），切出的小图也是 2560 分辨率下的尺寸
- 用户 2026-06 明确表态："过分割的时候都缩放成低分辨率了，小图用高分辨也提升不了什么"

---

## 7. 文件位置速查

| 文件 | 位置 |
|---|---|
| 前端按钮 + 触发函数 | [web/src/views/InferenceView.vue:46](web/src/views/InferenceView.vue:46), [:606](web/src/views/InferenceView.vue:606) |
| 后端路由 | [server/routers/inference.py:774](server/routers/inference.py:774) `crop_defects_for_classifier` |
| 单张切图规则 | [server/routers/inference.py:734](server/routers/inference.py:734) `_crop_defect_for_classifier` |
| DB 模型 | [server/models/inference_result.py](server/models/inference_result.py) `InferenceResult` |
| 类别名解析 | [server/routers/inference.py](server/routers/inference.py) `_resolve_class_names` |

---

## 8. 相关 endpoint

| Endpoint | 用途 |
|---|---|
| `POST /api/inference/crop-defects?project_id=X` | 切割小图打 zip（本文主题）|
| `POST /api/inference/run` | 上传图推理（multipart） |
| `POST /api/inference/run-by-image-id` | 按 image_id 推理（不上传，跳本地读，快 5-10×）|
| `GET /api/inference/project-images` | 项目图片抽样列表（推理训练图用） |

---

## TL;DR

1. 只 seg 项目能切，遍历项目所有推理记录里的 bbox
2. 切图分三档：长边 >512 缩到 512，128~512 原样切，<128 膨胀到 128
3. zip 按类别分文件夹，可直接喂 yolo-cls 训练二级分类模型
4. **bbox 是推理时缩放后坐标系**，必须先把原图缩到推理尺寸再切，否则全错位（这次会话已修）
5. 想要高清小图就推理时不缩放
